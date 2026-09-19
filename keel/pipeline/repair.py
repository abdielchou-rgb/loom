"""修复预算与冲突消解 —— 让「自动修订」有天花板、有仲裁、有边界。

    为什么要这个模块（研究证据）
    ────────────────────────────────────────────────────────────
    ConWriter（EMNLP 2026 Findings；arXiv 2608.05169）在 GPT-5、6K–12K
    长度上的实测结论是：**修复循环不收敛**。原因不是一个校验器写坏了，
    而是两个目标**互锁**：

        (a) 修复遵从 —— 把 critic 指出的问题改掉
        (b) 长度控制 —— 把篇幅压回目标区间

    改 (a) 会拉长篇幅，压 (b) 又会引入新的不一致；于是每一轮都是
    「修好一处、破坏另一处」，token 烧完时稿子停在原地。
    **验证器与生成器会互锁**，不设代价预算的修复循环会把预算烧在原地踏步上。

    Keel 现在的处境：
        `CriticLoop`（`keel/pipeline/engines.py`）只有 `max_rounds=2`
        这一个**次数**上限 —— 没有冲突消解、没有代价预算、没有长度解耦。
        次数上限挡不住互锁：它只保证「最多改两轮」，不保证那两轮不是
        互相抵消的两轮，也不保证一次修订不会顺手重写半章正文。

    三条机制（一一对应上面的三个缺口）
    ────────────────────────────────────────────────────────────
    1. **代价预算** `RepairBudget`：轮次 / 字段改动数 / tokens / 时长四条轴。
       触顶即停并**报告**（`spend()` 返回 `SpendOutcome`，`guard()` 抛
       `RepairBudgetExceeded`）。与 `budget.Budget` 的分工：那边管
       「**写**多少」，这边管「**改**多少」—— 同一趟跑里两笔账，不能混。
    2. **冲突消解** `detect_conflicts()`：同一个 (卡, 字段) 被两条互斥建议
       同时修改时，**不挑一条执行**，产出 `conflicted` 交人裁决 —— 复用
       `keel/ir/proposal.py` 已有的 `DiffStatus.CONFLICTED` 语义与状态机，
       不新造状态、不新造终态。
    3. **长度解耦** `RepairScope`：「本轮修复不重跑字数约束」是这个模块里的
       一等表达，不是调用方口头的约定。默认**关闭**长度重跑
       （`SCOPE_REPAIR`），要重跑必须显式拿 `SCOPE_LENGTH`。

    铁律：触顶必须停止并报告，绝不静默继续
    ────────────────────────────────────────────────────────────
    **静默降级与永不静默改写同源**：两者都是「机器做了一件作者不知道的事」。
    所以这里没有「额度不够就少改一点」的档位 ——
      * 触顶后 `spend()` **抛** `RepairBudgetExceeded`（不是静默记一笔）；
      * 触顶本身就写在 `render()` 那一行里，说得出是哪条轴、为什么停；
      * 冲突不裁决、不挑边，原样交人（`conflicted`）。
    出问题可以，别不吭声。

    方法论出处（本模块每一条设计都要能溯源）
    ────────────────────────────────────────────────────────────
    * ConWriter（arXiv 2608.05169）—— 代价预算与长度解耦的直接动机，见上。
    * Horvitz, E. (1999). "Principles of Mixed-Initiative User Interfaces".
      *Proceedings of CHI '99*, ACM: 159-166.
        —— 混合主动界面：系统置信度不足以自行决定时，**把控制权交回人**，
           而不是猜一个继续跑。落到本模块：两条建议互斥 → 机器不裁决，
           标 `conflicted` 交人（"directability" 原则）。
    * Amershi, S. et al. (2019). "Guidelines for Human-AI Interaction",
      *Proceedings of CHI '19*, ACM, Paper 3, guideline 6。
        —— 拒绝必须是廉价的一次性操作。因此 `mark_conflicted()` 只**翻状态**，
           不要求任何人给理由、不写回任何值（`after` 一个字节都不动）。
    * 状态机与终态语义**完全复用** `keel/ir/proposal.py`（`resolve()`）：
      `conflicted` 在那里已经定义为终态，本模块只负责**产出**这个状态，
      不去实现第二套。

    ── 边界语义（逐字定义，别猜；与 `budget.py` 同源，别各写一套）────
    四条轴统一用 **`已用量 >= 上限`** 作为跳闸判据：
      * `max_rounds=3`：改完 3 轮是合格产出，第 4 轮不会开始；计数到 3 时
        `exhausted()` 返回 `["rounds"]`。
      * `max_field_edits=5`：动过 5 个字段后停；**按不同字段去重计数**
        （见 `note_edit`），不是按改动次数。
      * `max_tokens=1000`：已用 999 不停，已用 1000 停。
      * `max_minutes=10.0`：跑了 599 秒不停，600 秒（恰好 10 分钟）停。
      * 上限为 `0` = 一开始就停（`0 >= 0` 成立）。
      * 上限为 `None` = 该轴**不限**，它永远不会出现在 `exhausted()` 里。
    用 `>=` 而不是 `>` 是刻意的：`>` 会让「恰好用完额度」的那一次继续往下走，
    天花板就漏了。硬停宁可早一拍。

    ── 时间全部可注入 ─────────────────────────────────────────────
    所有涉及时间的函数收 `now`（`time.time()` 语义，秒），测试注入 `now`，
    因此**不 sleep、不依赖真实时钟**。这条纪律与 `keel/clock.py`
    （`wall_iso(ts=None)`）同源：不取钟的结构才写得确定性的测试。
    本模块**不盖时间戳** —— `spend()` 只记账，`mark_conflicted()` 只翻状态，
    `decided_at` / `decided_by` 一律留给调用方（那是要举证的东西，
    机器不能替人填）。

    ── 诚实的局限（不要当它没说）────────────────────────────────────
    1. **只检字面冲突。** `detect_conflicts()` 认的是「同一个 (卡, 字段)
       被给出两个不同的 `after`」。改 `outcome` 与改 `value_charge_end`
       在叙事上互斥、但字段名不同 —— 这种**语义冲突查不出来**，
       本模块不会假装查出来了。
    2. **预算只在「单位之间」被检查。** 已经开始的那一轮一定会跑完
       （可能超支），本模块保证的是「不会无限修下去」，不是「token 恰好
       卡在 max_tokens」。
    3. **不计量。** tokens / 时长由调用方喂进来；喂错数字，这里也只能
       诚实地算错。
    4. **不做修复执行、不接入流水线。** 本模块只回答「还能不能改、
       会不会撞车」，改什么是 `CriticLoop` 的事（集成方统一接）。
    5. **字段改动按 (卡, 字段) 去重。** 于是「同一处来回复」不会烧这条轴
       —— 那是 `rounds` 轴的职责。这个取舍是有意的：按次数计费会让来回复
       更快触顶，反而把「修复不收敛」这个信号埋进一条无关的天花板里。

    纯记账：无 I/O、无网络、不 import 任何其它 `keel.pipeline` 模块
    （与 `budget.py` 同一约束，因此可以独立测试）。对提案只要求**鸭子类型**
    （见 `ProposalLike`），不 import IR 的具体模型 —— 唯一 import 的
    `DiffStatus` 是**语义常量**，不是数据结构。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

from ..ir.proposal import DiffStatus

__all__ = [
    "LENGTH_FIELDS",
    "Conflict",
    "ProposalLike",
    "RepairBudget",
    "RepairBudgetExceeded",
    "RepairScope",
    "SCOPE_LENGTH",
    "SCOPE_REPAIR",
    "SpendOutcome",
    "conflict_key",
    "detect_conflicts",
    "mark_conflicted",
]

#: 四条轴的固定顺序：`exhausted()` 的返回顺序、
#: `RepairBudgetExceeded.axes` 的顺序都由它决定 —— 顺序写死，日志才稳定可比。
_AXIS_ORDER = ("rounds", "field_edits", "tokens", "minutes")

_AXIS_LABELS = {
    "rounds": "轮次",
    "field_edits": "字段改动",
    "tokens": "tokens",
    "minutes": "时长",
}

#: 长度 / 字数相关字段。修复轮默认不重跑这些（见 `RepairScope`）。
#:
#: 这是 ConWriter 观察到的互锁的**落点**：正文与字数目标属于「长度控制」，
#: 与「修复遵从」是两个目标。把它们列出来不是为了禁改，而是为了让
#: 「这一轮到底要不要碰长度」成为一个**可以打在日志里的事实**，
#: 而不是每个调用点各自记得的一句口头约定。
LENGTH_FIELDS = frozenset({"prose", "target_words", "target_length", "length", "words"})


class ProposalLike(Protocol):
    """最小协议：长得像 `ir.proposal.Diff` 就够。

    刻意用 `Protocol` 而不是 `isinstance` 检查：修复预算不该成为 IR 的
    下游依赖（铁律：跨层共用的东西要么上移，要么不依赖）。运行期一律
    `getattr` 取属性，因此自定义的假提案、namedtuple、ORM 对象都能进。

    必需属性：`id` / `target_card` / `field` / `after` / `status`。
    `status` 与 `DiffStatus` 用 `==` 比较（`DiffStatus` 是 `str, Enum`，
    因此裸字符串 "rejected" 也能对上）—— 用 `is` 会把鸭子类型挡在门外。
    """

    id: str
    target_card: str
    field: str
    after: Any
    status: DiffStatus


# ---------------------------------------------------------------------------
# 长度解耦：本轮修复允许动什么
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairScope:
    """本轮修复的**作用域**：允许动哪些字段，以及要不要重跑字数约束。

    `enforce_length` 是这整个模块里最要紧的一个布尔值。

    默认 `False`（`SCOPE_REPAIR`）= **本轮修复不重跑字数约束**。
    这不是偷懒，是 ConWriter 那条教训的直接应用：长度控制与修复遵从
    是两个目标，放在同一轮里同时满足，就是它们互锁的**必要条件**。
    解耦的做法是分轮 —— 修复轮只管一致性，长度回到常规生成轮去收。
    需要重跑时显式拿 `SCOPE_LENGTH`，日志里也看得见是谁打开的。

    字段白/黑名单只是附加的护栏，可以都不设（空集 = 不限）。
    """

    enforce_length: bool = False
    """是否重跑字数约束。**默认 False**：修复轮不碰长度（见 ConWriter）。"""

    allow_fields: frozenset[str] = frozenset()
    """白名单。空集 = 不限制字段（只受长度解耦与黑名单约束）。"""

    deny_fields: frozenset[str] = frozenset()
    """黑名单。命中即禁改，优先级最高 —— 黑名单是「这里绝不能自动动」，
    白名单是「这轮只想动这些」，两者的语气不一样，冲突时听更硬的那个。"""

    def allows(self, field: str) -> bool:
        """这个字段本轮允许被改吗。

        判据顺序：黑名单 → 长度解耦 → 白名单。
        """
        if field in self.deny_fields:
            return False
        if not self.enforce_length and field in LENGTH_FIELDS:
            return False
        if self.allow_fields and field not in self.allow_fields:
            return False
        return True

    def render(self) -> str:
        """作用域的人话片段（供 `RepairBudget.render()` 拼进同一行）。"""
        length = "重跑字数约束" if self.enforce_length else "不重跑字数约束"
        if self.allow_fields:
            return f"本轮{length}（只动 {'、'.join(sorted(self.allow_fields))}）"
        if self.deny_fields:
            return f"本轮{length}（不动 {'、'.join(sorted(self.deny_fields))}）"
        return f"本轮{length}"


#: 修复轮默认作用域：**不重跑字数约束**（长度与修复解耦）。
SCOPE_REPAIR = RepairScope()

#: 显式打开长度重跑的作用域。要走这条路，调用方得是故意的。
SCOPE_LENGTH = RepairScope(enforce_length=True)


# ---------------------------------------------------------------------------
# 代价预算
# ---------------------------------------------------------------------------


@dataclass
class SpendOutcome:
    """一次 `spend()` 的结果：**记账已经生效，这里只报告**。

    属性：
        tripped: 本次记账后触顶的轴（空 = 还有额度）。
        message: 人读的一行（就是此刻 `render()` 的结果）。

    `stopped` 为真时必须停止这一轮修复 —— 不是崩溃，是**正常停止**
    （稿子是一致的，只是没修到作者想要的全部）。
    """

    tripped: list[str]
    message: str

    @property
    def stopped(self) -> bool:
        return bool(self.tripped)


class RepairBudgetExceeded(RuntimeError):
    """修复预算到顶 —— **干净的停止信号，不是故障**。

    属性：
        axes: 触发停止的轴名，如 `["rounds", "tokens"]`，顺序同 `_AXIS_ORDER`。

    与 `budget.BudgetExceeded` 同理：调用方应当捕获它并干净收尾
    （把已修的状态落盘 + 记一条「因修复预算停止」的日志 + 成功退出），
    不要让它冒泡成堆栈追踪，也不要和校验器崩溃混为一谈。
    """

    def __init__(self, axes: list[str], message: str | None = None) -> None:
        self.axes: list[str] = list(axes)
        if message is None:
            labels = "、".join(_AXIS_LABELS.get(a, a) for a in self.axes)
            message = f"修复预算到顶：{labels} —— 停止修复，这是正常停止，不是故障"
        super().__init__(message)


@dataclass
class RepairBudget:
    """一次修复过程的账本：四条轴的上限 + 已用量 + 作用域。

    ── 为什么上限和已用量在同一个对象里（`budget.Budget` 是分开的）────
    `budget.Budget` / `Usage` 分开是对的：那边是**跨轮复用**的常量配置，
    用量每轮重建。而修复预算是**一次修复过程**的账本 —— 上限与已用量
    同生共死，没有「把这份已用量配到另一个上限上」这种用法。
    强行拆开只会要求调用方同时持有两个对象并在每次记账时对齐它们，
    而**对不齐的那一次不会有任何报错**，只会默默记到别人的账上。

    字段（前四个是上限，`None` = 该轴不限）：
        max_rounds        最多改几轮
        max_field_edits   最多动多少个**不同的** (卡, 字段)
        max_tokens        最多烧多少 tokens
        max_minutes       最多跑多少分钟（相对 `started_at`）
        scope             本轮作用域（长度解耦，见 `RepairScope`）
    已用量：
        rounds / field_edits / tokens / started_at / edit_keys

    ⚠ `started_at` 默认 `0.0`：设了 `max_minutes` 却不注入起点，算出来的
    elapsed 会是天文数字并**立刻跳闸** —— 那不是 bug，那是这个默认值的
    诚实含义（「未设置」）。调用方要么注入 `started_at=time.time()`，
    要么把 `max_minutes` 留空。
    """

    max_rounds: int | None = None
    max_field_edits: int | None = None
    max_tokens: int | None = None
    max_minutes: float | None = None

    scope: RepairScope = field(default_factory=lambda: SCOPE_REPAIR)

    rounds: int = 0
    field_edits: int = 0
    tokens: int = 0
    started_at: float = 0.0
    #: 已计过费的 (卡, 字段) 键。`note_edit()` 的去重依据。
    edit_keys: set[str] = field(default_factory=set)

    # -- 查询（纯函数，不改动任何状态，可反复调用）--

    def exhausted(self, *, now: float | None = None) -> list[str]:
        """哪些轴已经到顶。空列表 = 还能继续修。

        判据 `已用量 >= 上限`（见模块文档「边界语义」）。`None` 上限的轴
        永不出现在这里。返回顺序固定为 轮次 → 字段改动 → tokens → 时长。
        """
        tripped: list[str] = []

        if self.max_rounds is not None and self.rounds >= self.max_rounds:
            tripped.append("rounds")

        if self.max_field_edits is not None and self.field_edits >= self.max_field_edits:
            tripped.append("field_edits")

        if self.max_tokens is not None and self.tokens >= self.max_tokens:
            tripped.append("tokens")

        if self.max_minutes is not None:
            elapsed = _now(now) - self.started_at
            if elapsed >= self.max_minutes * 60.0:
                tripped.append("minutes")

        return tripped

    def should_stop(self, *, now: float | None = None) -> bool:
        """是否应当停止。`exhausted()` 的布尔版本，两者判据永远一致。"""
        return bool(self.exhausted(now=now))

    def remaining(self, *, now: float | None = None) -> dict:
        """每条轴还剩多少。

        键：`rounds` / `field_edits` / `tokens` / `minutes`，外加恒有的
        `elapsed_minutes`。

        * 上限为 `None`（不限）→ 值是 `None`，**不是** `0`、不是 `inf`：
          「还剩多少」这个问题对不限的轴没有答案。
        * 已超支的轴 → 值是负的（如实报告超了多少）。
        * 不做任何除法求比例，因此不存在除零。
        """
        elapsed_minutes = (_now(now) - self.started_at) / 60.0

        return {
            "rounds": (
                None if self.max_rounds is None else self.max_rounds - self.rounds
            ),
            "field_edits": (
                None
                if self.max_field_edits is None
                else self.max_field_edits - self.field_edits
            ),
            "tokens": (
                None if self.max_tokens is None else self.max_tokens - self.tokens
            ),
            "minutes": (
                None
                if self.max_minutes is None
                else self.max_minutes - elapsed_minutes
            ),
            "elapsed_minutes": elapsed_minutes,
        }

    def render(self, *, now: float | None = None) -> str:
        """一行给人看的运行日志（跑到一半时也该有用：说清还剩多少、动不动长度）。

        单行、无换行、无术语、无表情。到顶时开头写「修复预算到顶」并列出轴名，
        同时明说这是正常停止；没到顶时开头写「修复继续」。
        末尾恒带作用域片段 —— 「本轮不重跑字数约束」要能被**看见**，
        不能只是调用方心里记得。
        """
        ts = _now(now)
        tripped = self.exhausted(now=ts)
        rem = self.remaining(now=ts)

        parts = [
            _seg("轮次", self.rounds, self.max_rounds, rem["rounds"], str, " 轮"),
            _seg(
                "字段改动",
                self.field_edits,
                self.max_field_edits,
                rem["field_edits"],
                str,
                " 处",
            ),
            _seg("已用", self.tokens, self.max_tokens, rem["tokens"], str, " tokens"),
            _seg(
                "已跑",
                rem["elapsed_minutes"],
                self.max_minutes,
                rem["minutes"],
                lambda v: f"{v:.1f}",
                " 分钟",
            ),
        ]

        if tripped:
            labels = "、".join(_AXIS_LABELS.get(a, a) for a in tripped)
            head = f"修复预算到顶（{labels}）—— 停止修复，这是正常停止，不是故障"
        else:
            head = "修复继续"

        return f"{head} · " + " · ".join(parts) + f" · {self.scope.render()}"

    def allows(self, field: str) -> bool:
        """本轮作用域是否允许改这个字段。委托给 `scope`（长度解耦的唯一入口）。"""
        return self.scope.allows(field)

    # -- 记账（唯一的变更入口）--

    def guard(self, *, now: float | None = None) -> None:
        """到顶就抛 `RepairBudgetExceeded`；没到顶就安静返回 `None`。

        **这是硬停，不是崩溃。** 抛异常只是为了让循环的收尾逻辑集中在一处
        （`except RepairBudgetExceeded`），而不是让每一层都去判断布尔值。
        """
        tripped = self.exhausted(now=now)
        if tripped:
            raise RepairBudgetExceeded(tripped)

    def spend(
        self,
        *,
        rounds: int = 0,
        field_edits: int = 0,
        tokens: int = 0,
        now: float | None = None,
    ) -> SpendOutcome:
        """记一笔账，并**报告**记完之后是否触顶。

        语义（`budget.check()` 的镜像，多了一步「记账」）：
          1. 记账**之前**若已经触顶 → **抛** `RepairBudgetExceeded`。
             触顶之后再记账就是「静默继续」，那正是本模块要消灭的东西 ——
             所以这里不返回、不警告，直接炸。
          2. 否则累加，然后返回 `SpendOutcome`；`outcome.tripped` 非空表示
             **这一笔把额度用完了**，调用方必须在这一轮结束后停止。

        于是「恰好用满」的那一笔仍然被记上（稿子不会停在一半），
        而下一笔拿不到沉默的许可。
        """
        ts = _now(now)
        already = self.exhausted(now=ts)
        if already:
            raise RepairBudgetExceeded(already)

        self.rounds += rounds
        self.field_edits += field_edits
        self.tokens += tokens

        tripped = self.exhausted(now=ts)
        return SpendOutcome(tripped=tripped, message=self.render(now=ts))

    def note_edit(self, target_card: str, field: str) -> bool:
        """记一次「动了这个字段」，**同一 (卡, 字段) 只计一次**。

        返回：本次是否**新**计了一笔（True）/ 之前已经计过（False，不重复计费）。

        为什么按 (卡, 字段) 去重而不是按次数：`max_field_edits` 度量的是
        **修复的波及面**（这一次修复动了多少地方），不是「模型改了多少次」。
        同一个字段被三轮反复改是**不收敛的信号**，它该由 `rounds` 轴去掐；
        按次数计费会让来回复更快触顶，把这个信号埋进一条无关的账里
        （见模块文档「诚实的局限」第 5 条）。
        """
        key = conflict_key(target_card, field)
        if key in self.edit_keys:
            return False
        self.edit_keys.add(key)
        self.spend(field_edits=1)
        return True


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def _seg(
    label: str,
    used: float,
    cap: float | None,
    rem: float | None,
    fmt,
    unit: str = "",
) -> str:
    """一段「已用/上限（还剩）」的人话。

    与 `budget._seg` 同形但刻意各存一份：那边是私有符号，跨模块 import
    私有函数会让预算层反向成为修复层的依赖（铁律：跨层共用的东西该上移，
    不是反向引用）。
    """
    if cap is None:
        return f"{label} {fmt(used)}{unit}（不限）"
    if rem is not None and rem <= 0:
        return f"{label} {fmt(used)}/{fmt(cap)}{unit}（已到顶）"
    return f"{label} {fmt(used)}/{fmt(cap)}（还剩 {fmt(rem)}{unit}）"


# ---------------------------------------------------------------------------
# 冲突消解
# ---------------------------------------------------------------------------


def conflict_key(target_card: str, field: str) -> str:
    """冲突的分组键：`卡::字段`。

    同一处改动 = 同一个键。用 `::` 而不是 `:` 是因为 `target_card` 本身
    形如 `scene:sc3`（见 `Proposer`），裸 `:` 拼接会有歧义。
    """
    return f"{target_card}::{field}"


@dataclass(frozen=True)
class Conflict:
    """一处**字面冲突**：同一个 (卡, 字段) 被给出了两个以上不同的提案值。

    字段：
        target_card / field  冲突发生的位置
        proposal_ids         互斥的提案 id，**按 id 排序**（保证对称）
        values               与 `proposal_ids` 一一对应的竞争值

    ⚠ 只有**字面**冲突可被检出：同字段不同值。改 `outcome` 与改
    `value_charge_end` 在叙事上互斥、字段名却不同 —— 那种语义冲突
    本模块查不出来，也不会假称查出来了（见模块文档「诚实的局限」第 1 条）。
    """

    target_card: str
    field: str
    proposal_ids: tuple[str, ...]
    values: tuple[Any, ...]

    @property
    def key(self) -> str:
        return conflict_key(self.target_card, self.field)

    def render(self) -> str:
        """一行人话（进日志 / 进提案界面）。"""
        ids = " / ".join(self.proposal_ids)
        return (
            f"{self.key} 有 {len(self.proposal_ids)} 条互斥建议（{ids}），"
            "已标为 conflicted 交人裁决（终态）"
        )


def _pid(p: Any) -> str:
    return str(getattr(p, "id"))


def _card(p: Any) -> str:
    return str(getattr(p, "target_card"))


def _fld(p: Any) -> str:
    return str(getattr(p, "field"))


def _status(p: Any) -> Any:
    """提案状态。`DiffStatus` 是 `str, Enum`，故一律用 `==` 比较，不用 `is`。

    用 `is` 会把「status 是裸字符串 'rejected'」的鸭子类型对象误判成
    「不是任何已知状态」，从而把它拉进冲突检测 —— 一个静默的反直觉。
    """
    return getattr(p, "status", None)


def detect_conflicts(proposals: Sequence[Any] | Iterable[Any]) -> list[Conflict]:
    """找出互斥建议。**纯函数**：不改任何提案，不取时钟，可反复调用。

    判据（三条，缺一不可）：
      1. 同一个 `(target_card, field)`；
      2. **两条以上不同 id** 的提案（同一条被传两次不算 —— 自反）；
      3. `after` **不同**（值相同 = 两条建议其实一致 = 不算冲突）。

    被**拒绝**（`rejected`）的提案不参与：它已经被人否掉了，不改任何东西，
    构不成冲突。已 `conflicted` 的提案**参与** —— 它仍在等人裁决，
    冲突依然成立；重跑只是把它再报一次（`mark_conflicted` 幂等，不会翻倍）。

    对称：结果只取决于集合内容，与输入顺序无关（`proposal_ids` 按 id 排序）。
    """
    groups: dict[str, list[tuple[str, Any]]] = {}
    seen: set[str] = set()

    for p in proposals:
        pid = _pid(p)
        if pid in seen:
            continue  # 同一条建议重复传入 = 自反，不是两条建议
        seen.add(pid)
        if _status(p) == DiffStatus.REJECTED:
            continue
        key = conflict_key(_card(p), _fld(p))
        groups.setdefault(key, []).append((pid, getattr(p, "after")))

    out: list[Conflict] = []
    for key in sorted(groups):
        card, _, fname = key.partition("::")
        # 先按 id 排序 → 结果与输入顺序无关（对称）
        pairs = sorted(groups[key], key=lambda kv: kv[0])
        distinct: list[tuple[str, Any]] = []
        for pid, value in pairs:
            if not any(value == existing for _, existing in distinct):
                distinct.append((pid, value))
        if len(distinct) < 2:
            continue  # 只有一种声音，不是冲突
        out.append(
            Conflict(
                target_card=card,
                field=fname,
                proposal_ids=tuple(pid for pid, _ in distinct),
                values=tuple(value for _, value in distinct),
            )
        )
    return out


def mark_conflicted(
    proposals: Sequence[Any] | Iterable[Any],
    *,
    conflicts: Sequence[Conflict] | None = None,
) -> list[Any]:
    """把冲突涉及的提案标为 `DiffStatus.CONFLICTED`，交人裁决。

    **复用 `ir/proposal.py` 的既有语义，不新造状态**：`conflicted` 在那里
    已经定义为终态（反向裁决的结果），本模块只负责**产出**这个状态。
    机器在两条互斥建议之间挑一条执行，是 Horvitz 1999 明令禁止的那种
    「系统猜一个继续跑」。

    返回**本次新翻**的提案列表：
      * 已经是 `conflicted` 的不重复计入（终态幂等 —— 遥测不会因重跑翻倍）；
      * `rejected` 的一律不碰（它不参与冲突，见 `detect_conflicts`）；
      * **不写 `after`、不写 `decided_at` / `decided_by`** —— 本模块无时钟，
        而「谁在什么时候裁决」是要举证的东西，只能由调用方填。
    """
    found = list(detect_conflicts(proposals)) if conflicts is None else list(conflicts)
    keys = {c.key for c in found}
    if not keys:
        return []

    marked: list[Any] = []
    for p in proposals:
        if conflict_key(_card(p), _fld(p)) not in keys:
            continue
        if _status(p) == DiffStatus.REJECTED:
            continue
        if _status(p) == DiffStatus.CONFLICTED:
            continue  # 终态：不再翻转
        p.status = DiffStatus.CONFLICTED
        marked.append(p)
    return marked
