"""预算闸门（loom.pipeline.budget）—— 测试先行，含变异验证。

跑法：
    .venv/Scripts/python.exe tests/test_budget.py

零依赖（不用 pytest），与 `tests/test_workbuddy_gen.py` 同风格：
一个极简 `T`（ok/eq）+ `main() -> int`，失败返回非 0（`scripts/verify.py`
会 glob `tests/test_*.py` 并跑，所以退出码必须诚实）。

── 为什么一个「只是比大小」的模块也值得这样测 ──────────────────
因为它是**无人值守写作的唯一刹车**。它若 silently 少报一条轴，或者边界上
差一（`>` 写成 `>=`、或 `>=` 写成 `>`），后果不是测试变红，而是：
作者在睡觉，钱在烧。所以这里钉死三件事：

  1. 每条轴该跳的跳、不该跳的不跳，**边界 N 与 N+1 逐一对拍**
  2. `None` = 该轴真的不限（不是「当 0 处理」那种静默反直觉）
  3. `check()` / `should_stop()` / `exceeded()` 三者判据**永远一致** ——
     循环用其中任何一个收尾，结果都得一样

时间全部注入 `now`，不 sleep、不碰真实时钟，因此每次跑结果完全一致。

── 期望值的来源 ─────────────────────────────────────────────────
判据是「已用量 >= 上限」（>= 而不是 >，见模块文档「边界语义」：
`max_scenes=3` 表示写完 3 场是合格产出，计数到 3 时跳闸，第 4 场不会开始）。
期望值全部由这条定义推出，不是从实现里抄回来的；数值特意选二进制可精确
表示的（0.5 / 1.5 / 2.0 / 600 秒），避免浮点噪声掩盖真正的逻辑错误。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.pipeline.budget import (  # noqa: E402
    Budget,
    BudgetExceeded,
    Usage,
    check,
    exceeded,
    remaining,
    render,
    should_stop,
)


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"  ✓ {label}")
        else:
            self.failed.append(label)
            print(f"  ✗ {label}" + (f"\n      {detail}" if detail else ""))

    def eq(self, got, want, label: str) -> None:
        self.ok(got == want, label, f"期望 {want!r}，实际 {got!r}")

    def group(self, name: str) -> None:
        print(f"\n── {name} ──")


# 起点固定为 1000.0 秒；随后用 +N 秒表示「跑了 N 秒」。
T0 = 1000.0


# ---------------------------------------------------------------------------
# 1. 单轴：该跳的跳、不该跳的不跳
# ---------------------------------------------------------------------------


def test_each_axis(t: T) -> None:
    t.group("1. 四条轴各自跳闸 / 不跳闸")

    # 场次
    b = Budget(max_scenes=3)
    t.eq(exceeded(b, Usage(scenes=2)), [], "场次 2/3 → 不停")
    t.eq(exceeded(b, Usage(scenes=3)), ["scenes"], "场次 3/3 → 跳（第 4 场不会开始）")

    # tokens
    b = Budget(max_tokens=1000)
    t.eq(exceeded(b, Usage(tokens=999)), [], "tokens 999/1000 → 不停")
    t.eq(exceeded(b, Usage(tokens=1000)), ["tokens"], "tokens 1000/1000 → 跳")

    # 花费
    b = Budget(max_cost=2.0)
    t.eq(exceeded(b, Usage(cost=1.99)), [], "花费 1.99/2.00 → 不停")
    t.eq(exceeded(b, Usage(cost=2.0)), ["cost"], "花费 2.00/2.00 → 跳")

    # 时长（10 分钟 = 600 秒）
    b = Budget(max_minutes=10.0)
    t.eq(
        exceeded(b, Usage(started_at=T0), now=T0 + 599.0),
        [],
        "跑了 599 秒 → 不停",
    )
    t.eq(
        exceeded(b, Usage(started_at=T0), now=T0 + 600.0),
        ["minutes"],
        "跑了 600 秒（恰好 10 分钟）→ 跳",
    )

    # 未设上限的轴不会串台：只报出设了上限的那条
    b = Budget(max_scenes=None, max_tokens=1000)
    t.eq(
        exceeded(b, Usage(scenes=10**6, tokens=10)),
        [],
        "场次不限时，10 万场也不报",
    )


# ---------------------------------------------------------------------------
# 2. None = 该轴不限（不是 0，不是「永远停」）
# ---------------------------------------------------------------------------


def test_none_is_unlimited(t: T) -> None:
    t.group("2. None = 该轴不限")

    # 空预算：用量再离谱也永不停止
    empty = Budget()
    huge = Usage(scenes=10**9, tokens=10**12, cost=1e9, started_at=0.0)
    t.eq(exceeded(empty, huge, now=1e12), [], "空预算 + 天文数字用量 → 不跳")
    t.ok(not should_stop(empty, huge, now=1e12), "空预算 should_stop = False")
    try:
        check(empty, huge, now=1e12)
        t.ok(True, "空预算 check() 不抛")
    except BudgetExceeded as exc:
        t.ok(False, "空预算 check() 不该抛", f"抛了：{exc}")

    # 逐条轴：把该轴设为 None，其余轴设成已超，则该轴不得出现在结果里
    over = Usage(scenes=99, tokens=99, cost=99.0, started_at=T0)
    far = T0 + 10**6
    t.eq(
        exceeded(Budget(max_tokens=1, max_cost=1.0, max_minutes=1.0), over, now=far),
        ["tokens", "cost", "minutes"],
        "场次=None：其余三条照报",
    )
    t.eq(
        exceeded(Budget(max_scenes=1, max_cost=1.0, max_minutes=1.0), over, now=far),
        ["scenes", "cost", "minutes"],
        "tokens=None：其余三条照报",
    )
    t.eq(
        exceeded(Budget(max_scenes=1, max_tokens=1, max_minutes=1.0), over, now=far),
        ["scenes", "tokens", "minutes"],
        "cost=None：其余三条照报",
    )
    t.eq(
        exceeded(Budget(max_scenes=1, max_tokens=1, max_cost=1.0), over, now=far),
        ["scenes", "tokens", "cost"],
        "minutes=None：其余三条照报",
    )


# ---------------------------------------------------------------------------
# 3. 边界：N 与 N+1 逐一对拍
# ---------------------------------------------------------------------------


def test_boundaries(t: T) -> None:
    t.group("3. 边界 N / N+1")

    # 场次：max=3 → 写完 3 场是合格产出；计数到 3 时跳，第 4 场不会开始
    b = Budget(max_scenes=3)
    t.eq(exceeded(b, Usage(scenes=1)), [], "1 场后继续")
    t.eq(exceeded(b, Usage(scenes=2)), [], "2 场后继续（第 3 场照写）")
    t.eq(exceeded(b, Usage(scenes=3)), ["scenes"], "3 场后停（第 4 场不开）")
    t.eq(exceeded(b, Usage(scenes=4)), ["scenes"], "4 场（已超 1）照停")

    # tokens：1000 是额度，花到 1000 就停，不是 1001
    b = Budget(max_tokens=1000)
    t.eq(exceeded(b, Usage(tokens=998)), [], "998 → 不停")
    t.eq(exceeded(b, Usage(tokens=999)), [], "999 → 不停")
    t.eq(exceeded(b, Usage(tokens=1000)), ["tokens"], "1000 → 停（>= 而非 >）")
    t.eq(exceeded(b, Usage(tokens=1001)), ["tokens"], "1001 → 停")

    # 花费
    b = Budget(max_cost=2.0)
    t.eq(exceeded(b, Usage(cost=1.5)), [], "1.5 → 不停")
    t.eq(exceeded(b, Usage(cost=2.0)), ["cost"], "2.0 → 停")
    t.eq(exceeded(b, Usage(cost=2.5)), ["cost"], "2.5 → 停")

    # 时长：600 秒是边界
    b = Budget(max_minutes=10.0)
    t.eq(exceeded(b, Usage(started_at=T0), now=T0 + 0.0), [], "刚起步 → 不停")
    t.eq(exceeded(b, Usage(started_at=T0), now=T0 + 599.9), [], "599.9 秒 → 不停")
    t.eq(exceeded(b, Usage(started_at=T0), now=T0 + 600.0), ["minutes"], "600 秒 → 停")
    t.eq(exceeded(b, Usage(started_at=T0), now=T0 + 600.1), ["minutes"], "600.1 秒 → 停")

    # 上限为 0 = 一开始就停（0 >= 0）
    t.eq(exceeded(Budget(max_scenes=0), Usage()), ["scenes"], "max_scenes=0 → 立刻停")


# ---------------------------------------------------------------------------
# 4. 多条轴同时跳闸 → 全部报出（不是只报第一条）
# ---------------------------------------------------------------------------


def test_multiple_axes(t: T) -> None:
    t.group("4. 多轴同时跳闸")

    b = Budget(max_scenes=3, max_tokens=1000, max_cost=2.0, max_minutes=10.0)
    t.eq(
        exceeded(b, Usage(scenes=5, tokens=5000, cost=9.5, started_at=T0), now=T0 + 3600),
        ["scenes", "tokens", "cost", "minutes"],
        "四条全超 → 四条全报，顺序固定",
    )

    b = Budget(max_scenes=3, max_tokens=10**9, max_cost=2.0, max_minutes=10.0)
    t.eq(
        exceeded(b, Usage(scenes=3, tokens=7, cost=8.0, started_at=T0), now=T0 + 30),
        ["scenes", "cost"],
        "只报超了的两条（tokens 未超、时间未到）",
    )

    t.eq(
        exceeded(
            Budget(max_scenes=99, max_tokens=99, max_cost=99.0),
            Usage(scenes=1, tokens=1, cost=1.0, started_at=T0),
            now=T0 + 3600,
        ),
        [],
        "全都在额度内 → 空列表（minutes 未设，不报）",
    )


# ---------------------------------------------------------------------------
# 5. check / should_stop / exceeded 三者一致
# ---------------------------------------------------------------------------


def _cases():
    b_all = Budget(max_scenes=3, max_tokens=1000, max_cost=2.0, max_minutes=10.0)
    return [
        ("空预算", Budget(), Usage(scenes=99, tokens=99, cost=99.0, started_at=T0), T0 + 10**6),
        ("刚起步", b_all, Usage(scenes=0, tokens=0, cost=0.0, started_at=T0), T0 + 1.0),
        ("用一半", b_all, Usage(scenes=1, tokens=500, cost=1.0, started_at=T0), T0 + 300.0),
        ("场次到顶", b_all, Usage(scenes=3, tokens=10, cost=0.1, started_at=T0), T0 + 30.0),
        ("tokens 到顶", b_all, Usage(scenes=1, tokens=1000, cost=0.1, started_at=T0), T0 + 30.0),
        ("花费到顶", b_all, Usage(scenes=1, tokens=10, cost=2.0, started_at=T0), T0 + 30.0),
        ("时长到顶", b_all, Usage(scenes=1, tokens=10, cost=0.1, started_at=T0), T0 + 600.0),
        (
            "全超",
            b_all,
            Usage(scenes=9, tokens=9999, cost=99.0, started_at=T0),
            T0 + 9999.0,
        ),
    ]


def test_agreement(t: T) -> None:
    t.group("5. check / should_stop / exceeded 判据一致")

    for label, b, u, now in _cases():
        axes = exceeded(b, u, now=now)
        stop = should_stop(b, u, now=now)
        t.eq(stop, bool(axes), f"{label}：should_stop 与 exceeded 一致")

        raised = None
        try:
            check(b, u, now=now)
        except BudgetExceeded as exc:
            raised = exc
        t.eq(raised is not None, bool(axes), f"{label}：check 是否抛与 exceeded 一致")
        if raised is not None:
            t.eq(raised.axes, axes, f"{label}：异常携带的轴 == exceeded 的轴")


def test_exception_shape(t: T) -> None:
    t.group("6. BudgetExceeded 的形状（日志要说得清为什么停）")

    b = Budget(max_scenes=3, max_cost=2.0)
    try:
        check(b, Usage(scenes=3, cost=2.0), now=T0)
        t.ok(False, "到顶必须抛")
    except BudgetExceeded as exc:
        t.ok(isinstance(exc, RuntimeError), "是 RuntimeError 子类（可被循环收尾捕获）")
        t.eq(exc.axes, ["scenes", "cost"], "axes 携带触发的轴")
        t.ok("场次" in str(exc), f"消息里说得出是哪条轴：{exc}")
        t.ok("花费" in str(exc), f"消息里说得出是哪条轴：{exc}")

    # 消息不是空壳：只带一条轴时也能读
    try:
        check(Budget(max_minutes=1.0), Usage(started_at=T0), now=T0 + 60.0)
        t.ok(False, "时长到顶必须抛")
    except BudgetExceeded as exc:
        t.eq(exc.axes, ["minutes"], "axes 只含 minutes")
        t.ok("时长" in str(exc), f"消息可读：{exc}")


# ---------------------------------------------------------------------------
# 7. remaining：不限 = None（不是 0、不是 inf、不是除零）
# ---------------------------------------------------------------------------


def test_remaining(t: T) -> None:
    t.group("7. remaining：不限的轴给 None，不除零")

    b = Budget(max_scenes=5, max_tokens=5000, max_cost=2.0, max_minutes=10.0)
    u = Usage(scenes=2, tokens=1200, cost=0.5, started_at=T0)
    r = remaining(b, u, now=T0 + 180.0)  # 跑了 3 分钟
    t.eq(r["scenes"], 3, "还剩 3 场")
    t.eq(r["tokens"], 3800, "还剩 3800 tokens")
    t.eq(r["cost"], 1.5, "还剩 ¥1.50")
    t.eq(r["minutes"], 7.0, "还剩 7.0 分钟")
    t.eq(r["elapsed_minutes"], 3.0, "已跑 3.0 分钟")

    # 不限的轴：None，不是 0（0 会被误读成「已用完」）
    r = remaining(Budget(), u, now=T0 + 180.0)
    t.eq(r["scenes"], None, "场次不限 → None")
    t.eq(r["tokens"], None, "tokens 不限 → None")
    t.eq(r["cost"], None, "花费不限 → None")
    t.eq(r["minutes"], None, "时长不限 → None")
    t.eq(r["elapsed_minutes"], 3.0, "elapsed_minutes 恒有")

    # 完全没跑过、全不限：不得出现除零 / nan / inf
    r0 = remaining(Budget(), Usage(), now=0.0)
    t.eq(r0["elapsed_minutes"], 0.0, "零时零起点 → 0.0，不是除零")
    t.ok(
        all(v is None or v == v and abs(v) != float("inf") for v in r0.values()),
        "无 nan / inf",
    )

    # 混合：只有一条轴限时
    r = remaining(Budget(max_tokens=100), Usage(tokens=30), now=0.0)
    t.eq(r["tokens"], 70, "只有 tokens 限时 → 70")
    t.eq(r["scenes"], None, "其余轴 None")

    # 已超支：如实给负数（不是被夹到 0）
    r = remaining(Budget(max_scenes=3, max_cost=2.0), Usage(scenes=5, cost=2.5), now=0.0)
    t.eq(r["scenes"], -2, "超 2 场 → -2")
    t.ok(r["cost"] < 0, "花费超支 → 负数")

    # 上限 0：还剩 0（与时间无关）
    t.eq(remaining(Budget(max_scenes=0), Usage(), now=0.0)["scenes"], 0, "max=0 → 剩 0")


# ---------------------------------------------------------------------------
# 8. render：一行人话，跑一半也该有用
# ---------------------------------------------------------------------------


def test_render(t: T) -> None:
    t.group("8. render：单行人话")

    b = Budget(max_scenes=5, max_tokens=5000, max_cost=2.0, max_minutes=10.0)
    u = Usage(scenes=2, tokens=1200, cost=0.5, started_at=T0)
    line = render(b, u, now=T0 + 180.0)
    t.ok(isinstance(line, str) and line.strip() != "", "非空字符串")
    t.ok("\n" not in line, "单行（无换行）")
    t.ok("继续写作" in line, "未到顶 → 开头写「继续写作」")
    t.ok("还剩 3 场" in line, f"说清还剩几场：{line}")
    t.ok("还剩 3800" in line, f"说清还剩多少 tokens：{line}")
    t.ok("还剩 ¥1.50" in line, f"说清还剩多少钱：{line}")
    t.ok("还剩 7.0 分钟" in line, f"说清还剩多少时间：{line}")

    # 不限的轴写成「不限」，而不是印一个不存在的上限
    line = render(Budget(max_scenes=5), Usage(scenes=2, tokens=7, started_at=T0), now=T0)
    t.ok("不限" in line, f"不限的轴写「不限」：{line}")
    t.ok("None" not in line and "null" not in line, "不把 None 印给人类看")

    # 到顶：说明为什么停，并明说这不是故障
    line = render(
        Budget(max_scenes=3, max_cost=2.0),
        Usage(scenes=3, cost=2.0, started_at=T0),
        now=T0,
    )
    t.ok("预算到顶" in line, f"到顶要写出来：{line}")
    t.ok("场次" in line and "花费" in line, f"说出是哪几条轴：{line}")
    t.ok("已到顶" in line, f"该轴标记为已到顶：{line}")
    t.ok("不是故障" in line, "明说这是正常停止（别被当成崩溃）")

    # 空预算也能渲染（不给空行）
    line = render(Budget(), Usage(scenes=1, started_at=T0), now=T0 + 60)
    t.ok(line.strip() != "", "空预算也有一行日志")
    t.ok("继续写作" in line, "空预算 → 继续写作")

    # 纯记账：不写文件、不 import 其它 pipeline 模块（这里只验证无副作用：
    # 反复渲染同一输入得到完全相同的行）
    t.eq(
        render(b, u, now=T0 + 180.0),
        render(b, u, now=T0 + 180.0),
        "同样输入 → 同样输出",
    )


# ---------------------------------------------------------------------------
# 9. 确定性：注入 now，与真实时钟无关
# ---------------------------------------------------------------------------


def test_determinism(t: T) -> None:
    t.group("9. 确定性（注入 now，不 sleep）")

    b = Budget(max_minutes=10.0)
    # 同一个「相对已跑时长」，无论绝对时间取多少，结论一致
    for base in (0.0, 1e6, 1.7e9):
        u = Usage(started_at=base)
        t.eq(exceeded(b, u, now=base + 599.0), [], f"base={base:g}：599 秒不停")
        t.eq(exceeded(b, u, now=base + 600.0), ["minutes"], f"base={base:g}：600 秒停")
        t.eq(
            remaining(b, u, now=base + 120.0)["minutes"],
            8.0,
            f"base={base:g}：已跑 2 分钟 → 剩 8.0",
        )

    # 不注入 now 时也不崩（走 time.time()）—— 只验证签名可用，不验证数值
    t.ok(isinstance(should_stop(Budget(max_scenes=1), Usage(scenes=5)), bool),
         "不传 now 也能跑（走真实时钟）")


# ---------------------------------------------------------------------------
# 10. 变异：故意改坏判据，本文件必须变红（见文件末尾说明与提交记录）
# ---------------------------------------------------------------------------


def test_mutation_guards(t: T) -> None:
    t.group("10. 变异护栏（这些断言曾抓到实现被改坏）")

    # 变异 A：把 `>=` 改成 `>`（边界差一）—— 恰好用满额度时必须仍然停
    t.eq(
        exceeded(Budget(max_scenes=3), Usage(scenes=3)),
        ["scenes"],
        "用满 3 场必须停（防 >= → >）",
    )
    t.eq(
        exceeded(Budget(max_tokens=1000), Usage(tokens=1000)),
        ["tokens"],
        "用满 1000 tokens 必须停（防 >= → >）",
    )

    # 变异 B：时间轴忘了乘 60（把分钟当秒）—— 10 分钟的额度不能 10 秒就跳
    t.eq(
        exceeded(Budget(max_minutes=10.0), Usage(started_at=T0), now=T0 + 10.0),
        [],
        "10 分钟额度下，10 秒不得跳（防漏 *60）",
    )

    # 变异 C：时间轴忘了减 started_at（直接用 now 当 elapsed）
    t.eq(
        exceeded(Budget(max_minutes=10.0), Usage(started_at=T0), now=T0 + 599.0),
        [],
        "elapsed 必须减去起点（防忽略 started_at）",
    )

    # 变异 D：多轴只报第一条（break / return 提前退出）
    t.eq(
        exceeded(
            Budget(max_scenes=1, max_tokens=1, max_cost=1.0, max_minutes=1.0),
            Usage(scenes=9, tokens=9, cost=9.0, started_at=T0),
            now=T0 + 600.0,
        ),
        ["scenes", "tokens", "cost", "minutes"],
        "四条都超必须报四条（防只报第一条）",
    )

    # 变异 E：remaining 把不限的轴算成 0 / inf
    r = remaining(Budget(), Usage(scenes=3, tokens=3, cost=3.0, started_at=T0), now=T0)
    t.ok(
        r["scenes"] is None and r["tokens"] is None and r["cost"] is None and r["minutes"] is None,
        "不限的轴必须是 None（防当成 0 / inf）",
    )

    # 变异 F：空预算被当成「全为 0 的上限」→ 一开局就停
    t.ok(
        not should_stop(Budget(), Usage(), now=T0),
        "空预算开局不得停（防 None 被当 0）",
    )


def main() -> int:
    t = T()
    print("═" * 64)
    print("  预算闸门（budget）—— 边界 / 不限 / 多轴 / 确定性 / 变异护栏")
    print("═" * 64)
    test_each_axis(t)
    test_none_is_unlimited(t)
    test_boundaries(t)
    test_multiple_axes(t)
    test_agreement(t)
    test_exception_shape(t)
    test_remaining(t)
    test_render(t)
    test_determinism(t)
    test_mutation_guards(t)

    print("\n" + "─" * 64)
    print(f"  通过 {t.passed} · 失败 {len(t.failed)}")
    if t.failed:
        for f in t.failed:
            print(f"    ✗ {f}")
        return 1
    print("  全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
