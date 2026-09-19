"""预算闸门：让「我不喊停就一直写」可以无人值守地跑。

作者的原话是「在我不喊停的时候，根据初始设计自动写作」。没有预算的自动写作
是**脱缰**：无人值守的生成会把 token 和钱一直烧下去，没有天花板。本模块就是
那天花板 —— 四条轴（场次 / token / 花费 / 时长）任意一条到顶，就停。

── 超预算是**硬停**，不是崩溃 ──────────────────────────────────
`check()` 抛 `BudgetExceeded`，调用方（自动写作循环）**应当捕获它并干净收尾**：
把已写出的内容落盘、写一条「因预算停止」的日志、退出码置 0。
这两件事必须分清楚：

  * 预算到顶 = 正常结束。稿件是完整的，只是没写满作者想要的长度。
  * 校验器崩溃 / 引擎异常 = 故障。稿件可能不完整，需要人工介入。

日志里绝不能把前者渲染成后者 —— 否则每次正常收尾都像一次事故，作者会开始
忽略日志，真正的故障也就没人看了。同理，`BudgetExceeded` **携带**是哪几条轴
（`exc.axes`）触发的，日志要说得出「为什么停」，而不是一句含糊的「出错了」。

── 边界语义（逐字定义，别猜）────────────────────────────────────
四条轴统一用 **`已用量 >= 上限`** 作为跳闸判据：

  * `max_scenes=3` 的意思是：**写完 3 场是合格的产出**；当计数到达 3 时
    `check()` 就跳，于是**第 4 场根本不会开始**。所以在计数 == 3 时
    `exceeded()` 返回 `["scenes"]` —— 那不是「多写了一场」，那是「到此为止」。
  * `max_tokens=1000`：已用 999 不停，已用 1000 停（额度已经花完）。
  * `max_cost=2.0`：已花 1.99 不停，已花 2.0 停。
  * `max_minutes=10.0`：跑了 599 秒不停，600 秒（恰好 10 分钟）停。
  * 上限为 `0` 代表「一开始就停」（`0 >= 0` 成立）。
  * 上限为 `None` 代表该轴**不限**，它永远不会出现在 `exceeded()` 里。

用 `>=` 而不是 `>` 是刻意的：`>` 会让「恰好花完额度」的那一次继续往下走，
超出额度，天花板就漏了。硬停宁可早一拍。

── 时间全部可注入 ───────────────────────────────────────────────
所有涉及时间的函数收 `now` 参数（`time.time()` 语义，秒）。
测试注入 `now`，因此**不 sleep、不依赖真实时钟**，结果完全确定。
不注入时才取 `time.time()`。

── 诚实的局限（不要当它没说）────────────────────────────────────
1. **预算只在「单位之间」被检查**。循环在写每一场之前/之后调用 `check()`，
   那么**已经开始的最后一场一定会超支**（可能超很多）。本模块是天花板，
   不是精确截断器；它保证的是「不会无限写下去」，不是「token 数恰好卡在
   max_tokens」。真正需要硬截断得靠引擎自己限制单次请求。
2. **本模块不计量**。`Usage.scenes/tokens/cost` 由调用方累加后传进来；
   这里不做 token 估算、不做汇率换算、不认币种（`render()` 里的 `¥` 只是
   一个展示符号）。喂错数字，这里也只能诚实地算错。
3. **没有预警档**。只有硬停，没有「已用 90%」的提醒 —— 需要提醒请调用方
   自己用 `remaining()` 算。
4. **不做持久化**。断线重跑的计数恢复是 checkpoint 模块的事，与这里无关。

纯记账：无 I/O、无网络、不依赖 IR、不 import 任何其它 `keel.pipeline` 模块
（因此可以独立测试）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

__all__ = [
    "Budget",
    "BudgetExceeded",
    "Usage",
    "check",
    "exceeded",
    "remaining",
    "render",
    "should_stop",
]

# 四条轴的固定顺序：`exceeded()` 的返回顺序、`BudgetExceeded.axes` 的顺序
# 都由它决定 —— 顺序写死，日志才稳定可比。
_AXIS_ORDER = ("scenes", "tokens", "cost", "minutes")

_AXIS_LABELS = {
    "scenes": "场次",
    "tokens": "tokens",
    "cost": "花费",
    "minutes": "时长",
}


@dataclass
class Budget:
    """四条轴的上限。`None` = 该轴不限。

    全为 `None`（默认）表示「随便写，永不因预算停止」—— 这是合法的，
    也是危险的，只在作者明确要求无上限时使用。
    """

    max_scenes: int | None = None
    max_tokens: int | None = None
    max_cost: float | None = None
    max_minutes: float | None = None


@dataclass
class Usage:
    """到目前为止的累计用量。

    `started_at` 用 `time.time()` 语义的秒；`0.0` 表示「未设置」，此时若
    又设了 `max_minutes`，算出来的 elapsed 会是天文数字并立刻跳闸 ——
    调用方要么注入真实起点，要么把 `max_minutes` 留空。
    """

    scenes: int = 0
    tokens: int = 0
    cost: float = 0.0
    started_at: float = 0.0


class BudgetExceeded(RuntimeError):
    """预算到顶 —— **干净的停止信号，不是故障**。

    属性：
        axes: 触发停止的轴名列表，如 `["scenes", "cost"]`，
              顺序同 `_AXIS_ORDER`（场次、tokens、花费、时长）。

    调用方应当**捕获它并正常收尾**（落盘 + 记一条「因预算停止」的日志 +
    成功退出），不要让它冒泡成堆栈追踪，也不要和校验器崩溃混为一谈。
    """

    def __init__(self, axes: list[str], message: str | None = None) -> None:
        self.axes: list[str] = list(axes)
        if message is None:
            labels = "、".join(_AXIS_LABELS.get(a, a) for a in self.axes)
            message = f"预算到顶：{labels}"
        super().__init__(message)


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def exceeded(
    budget: Budget,
    usage: Usage,
    *,
    now: float | None = None,
) -> list[str]:
    """哪些轴已经到顶。空列表 = 还能继续写。

    判据是 `已用量 >= 上限`（见模块文档「边界语义」）。`None` 上限的轴
    永不出现在这里。返回顺序固定为 场次 → tokens → 花费 → 时长。
    """
    tripped: list[str] = []

    if budget.max_scenes is not None and usage.scenes >= budget.max_scenes:
        tripped.append("scenes")

    if budget.max_tokens is not None and usage.tokens >= budget.max_tokens:
        tripped.append("tokens")

    if budget.max_cost is not None and usage.cost >= budget.max_cost:
        tripped.append("cost")

    if budget.max_minutes is not None:
        elapsed = _now(now) - usage.started_at
        if elapsed >= budget.max_minutes * 60.0:
            tripped.append("minutes")

    return tripped


def check(
    budget: Budget,
    usage: Usage,
    *,
    now: float | None = None,
) -> None:
    """到顶就抛 `BudgetExceeded`；没到顶就安静返回 `None`。

    **这是硬停，不是崩溃。** 抛异常只是为了让循环的收尾逻辑集中在一处
    （`except BudgetExceeded`），而不是让每一层都去判断一个布尔值。
    调用方必须捕获它并正常结束这一轮 —— 预算到顶的稿件是**完整稿件**，
    只是没写满作者想要的长度；它和「某个校验器炸了」是完全不同的两件事，
    日志里必须分开表述。
    """
    tripped = exceeded(budget, usage, now=now)
    if tripped:
        raise BudgetExceeded(tripped)


def should_stop(
    budget: Budget,
    usage: Usage,
    *,
    now: float | None = None,
) -> bool:
    """是否应当停止。`check()` 的布尔版本，两者判据永远一致。"""
    return bool(exceeded(budget, usage, now=now))


def remaining(
    budget: Budget,
    usage: Usage,
    *,
    now: float | None = None,
) -> dict:
    """每条轴还剩多少。

    键：`scenes` / `tokens` / `cost` / `minutes`，外加恒有的
    `elapsed_minutes`（已跑分钟数，无论是否限时）。

    * 上限为 `None`（不限）的轴 → 值是 `None`，**不是** `0`、不是 `inf`、
      也不是「减到负数」—— 「还剩多少」这个问题对不限的轴没有答案。
    * 已经超支的轴 → 值是负的（如实报告超了多少）。
    * 不做任何除法求比例，因此不存在除零。
    """
    elapsed_minutes = (_now(now) - usage.started_at) / 60.0

    return {
        "scenes": (
            None if budget.max_scenes is None else budget.max_scenes - usage.scenes
        ),
        "tokens": (
            None if budget.max_tokens is None else budget.max_tokens - usage.tokens
        ),
        "cost": (None if budget.max_cost is None else budget.max_cost - usage.cost),
        "minutes": (
            None
            if budget.max_minutes is None
            else budget.max_minutes - elapsed_minutes
        ),
        "elapsed_minutes": elapsed_minutes,
    }


def _seg(
    label: str,
    used: float,
    cap: float | None,
    rem: float | None,
    fmt,
    unit: str = "",
) -> str:
    """一段「已用/上限（还剩）」的人话。"""
    if cap is None:
        return f"{label} {fmt(used)}{unit}（不限）"
    if rem is not None and rem <= 0:
        return f"{label} {fmt(used)}/{fmt(cap)}{unit}（已到顶）"
    return f"{label} {fmt(used)}/{fmt(cap)}（还剩 {fmt(rem)}{unit}）"


def render(
    budget: Budget,
    usage: Usage,
    *,
    now: float | None = None,
) -> str:
    """一行给人看的运行日志（跑到一半时也该有用：说清还剩多少）。

    单行、无换行、无术语、无表情。到顶时开头写「预算到顶」并列出轴名，
    同时明说这是正常停止；没到顶时开头写「继续写作」。
    """
    tripped = exceeded(budget, usage, now=now)
    rem = remaining(budget, usage, now=now)
    elapsed_minutes = rem["elapsed_minutes"]

    parts = [
        _seg("已写", usage.scenes, budget.max_scenes, rem["scenes"], str, " 场"),
        _seg(
            "已用",
            usage.tokens,
            budget.max_tokens,
            rem["tokens"],
            str,
            " tokens",
        ),
        _seg(
            "花费",
            usage.cost,
            budget.max_cost,
            rem["cost"],
            lambda v: f"¥{v:.2f}",
        ),
        _seg(
            "已跑",
            elapsed_minutes,
            budget.max_minutes,
            rem["minutes"],
            lambda v: f"{v:.1f}",
            " 分钟",
        ),
    ]

    if tripped:
        labels = "、".join(_AXIS_LABELS.get(a, a) for a in tripped)
        head = f"预算到顶（{labels}）—— 停止写作，这是正常停止，不是故障"
    else:
        head = "继续写作"

    return f"{head} · " + " · ".join(parts)
