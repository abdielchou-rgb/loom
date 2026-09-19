"""决策遥测 —— 把「作者信不信任 AI 的提案」变成可查数据。

    方法论出处
    ────────────────────────────────────────────────────────────
    Ziegler, A., Kalliamvakou, E., Li, X. A., Rice, A., Rifkin, D.,
    Simister, S., Sittampalam, G., & Aftandilian, E. (2022).
    "Productivity Assessment of Neural Code Completion."
    *Proceedings of the 6th ACM SIGPLAN International Symposium on
    Machine Programming (MAPS '22)*: 21-29.
        —— 业界把「建议接受率 (acceptance rate)」确立为衡量 AI 建议
           是否有用的**核心产品指标**，并指出它必须被拆开看：整体接受率
           会掩盖「某类建议几乎没人用」。本文的按维度分布（by_source /
           by_target / by_field）就是这条结论的直接应用 —— 一个笼统的
           「采纳率 62%」无法指导任何调整，按维度拆开才能。

    Horvitz, E. (1999). "Principles of Mixed-Initiative User Interfaces".
    *Proceedings of CHI '99*, ACM: 159-166.
        —— 混合主动系统的收益取决于「提议的准确率」与「打扰的代价」之比。
           这个比值必须**可观测**，否则无法调参。

    本模块的目的，写在源项目自己的注释里，值得原样保留：

    > 「把『diff 接受率 / 拒绝率 / 来源→去向分布』变成可查数据，供周级
    >   门禁/产品调参（避免靠感觉判断『作者是否信任 AI 提案』）」

    也就是说：「作者信不信任 AI 的提案」这句话，要么是一个可以查询的
    数字，要么就只是一句感觉。本模块的全部价值就是把它变成前者。

    两条纪律
    ────────────────────────────────────────────────────────────
    1. **不碰时钟。** 时间戳一律作为参数传入（`decided_at`）。取
       `datetime.now()` 的结构写不出确定性测试，而一个测不准的指标会
       被当成噪声忽略掉 —— 那就退化回「靠感觉」了，本模块就白做了。
    2. **不落盘。** 纯内存 + 纯函数式读取。落盘属于台账
       （`keel/provenance/meter.py::ProvenanceLedger`）的职责；把「指标」
       和「记录」混在一起，会让指标被记录的持久化问题绑架。

    口径（三个数字的定义）
    ────────────────────────────────────────────────────────────
        裁决数 decisions = accepted + rejected + conflicted
                           （**pending 不是裁决**，是「还没发生的事」，
                             不进分母，也不进任何分布）
        accept_rate      = accepted / decisions，decisions == 0 时为 0.0

    `conflicted` **计入分母**：作者先接受再拒绝，是对该提案的不信任信号；
    把它排除在分母外会让采纳率虚高 —— 那正是本模块要防的「自欺指标」。

    三个分布数的是**裁决**，因此各自的合计恒等于 `decisions`。
    这不是巧合，是分区的定义。
"""

from __future__ import annotations

from pydantic import Field

from ..ir.base import KeelModel
from ..ir.proposal import Diff, DiffStatus


class DecisionRecord(KeelModel):
    """一次作者裁决的快照。

    刻意**复制**（而非引用）Diff 的字段，而不是存一个 Diff 对象：
    遥测要记录的是「裁决发生**当时**的提案长什么样」。若直接持有 Diff，
    后续对该 Diff 的改动（甚至 `conflicted` 翻转）会追溯性地改写历史，
    历史分布就不再可复现 —— 那样的指标没有意义。
    """

    diff_id: str = Field(min_length=1)
    status: DiffStatus = Field(description="裁决结果")
    source_card: str = Field(min_length=1, description="来源卡（从哪张卡传播过来）")
    target_card: str = Field(min_length=1, description="目标卡")
    field: str = Field(min_length=1, description="被改的字段")
    story_at: str | None = Field(
        default=None,
        description="**故事内**时点标签（如「第 3 章」）。**由调用方传入，本模块绝不取时钟。**"
        " 本字段服务于产品指标（哪几章的提案最常被采纳），**不是**墙钟时刻 ——"
        " 举证要看的墙钟在 `Diff.decided_at` 上。两者曾同名，现已分开。",
    )
    decided_by: str | None = Field(
        default=None,
        description="裁决主体（human / 机器 id）。用于把「机器代裁」从采纳率里摘出去 —— "
        "机器自己裁自己提的案子，采纳率必然虚高。",
    )


class DecisionTelemetry:
    """决策遥测台账。纯内存，无 I/O，无时钟。

    与 `ProvenanceLedger` 同源（都在 `keel/provenance/`），但记的不是
    「谁生成了这段文字」，而是「作者如何裁决 AI 的提案」——前者用于合规
    溯源，后者用于产品调参。
    """

    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    # -- 写入 --

    def record(
        self, diff: Diff, *, story_at: str | None = None
    ) -> DecisionRecord:
        """记录一次裁决。

        传入 `Diff` 而不是散装字段：避免调用方在转录 `source_card` /
        `target_card` / `field` 时写错（那类 bug 会让分布静默错位，
        且永远查不出来）。

        `pending` 的提案也会被记录（作者「还没裁决」这件事本身也是数据），
        但不会进入任何统计口径 —— 见 `decisions`。

        `decided_by` 从 `Diff` 上**抄**而不是另开参数：它与裁决同时落在
        Diff 上（见 `proposal.resolve` 的 `_stamp`），再让调用方传一次，
        就等于给了它第二次机会传得不一样 —— 而「裁决主体」这种字段一旦
        两处不一致，没人知道哪个是真的。
        """
        rec = DecisionRecord(
            diff_id=diff.id,
            status=diff.status,
            source_card=diff.source_card,
            target_card=diff.target_card,
            field=diff.field,
            story_at=story_at,
            decided_by=diff.decided_by,
        )
        self.records.append(rec)
        return rec

    # -- 读取 --

    @property
    def decisions(self) -> int:
        """已裁决数（pending 不算）。这是所有比率的共同分母。"""
        return sum(1 for r in self.records if r.status is not DiffStatus.PENDING)

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.records if r.status is DiffStatus.ACCEPTED)

    @property
    def rejected(self) -> int:
        return sum(1 for r in self.records if r.status is DiffStatus.REJECTED)

    @property
    def conflicted(self) -> int:
        return sum(1 for r in self.records if r.status is DiffStatus.CONFLICTED)

    @property
    def accept_rate(self) -> float:
        """采纳率 = 已接受 / 已裁决。

        零裁决返回 **0.0**（显式口径），不抛 ZeroDivisionError。
        一个刚上线、还没人用过的功能，采纳率是「无数据」而不是「100%」；
        返回 0.0 是保守选择 —— 宁可让仪表盘显示得悲观，也不要虚报。
        """
        n = self.decisions
        return self.accepted / n if n else 0.0

    def by_source_card(self) -> dict[str, int]:
        """按来源卡分布：哪张卡的改动最容易/最不容易被接受。"""
        return self._distribute(lambda r: r.source_card)

    def by_target_card(self) -> dict[str, int]:
        """按目标卡分布：AI 最常提议改哪张卡，其中多少被采纳。"""
        return self._distribute(lambda r: r.target_card)

    def by_field(self) -> dict[str, int]:
        """按字段分布：哪类字段（goal / wound / value_turn…）的提案最可信。"""
        return self._distribute(lambda r: r.field)

    def stats(self) -> dict:
        """机器可读汇总。供周级门禁与产品调参直接消费。

        输出**确定性**：分布按 key 排序，比率四舍五入到 4 位，
        因此可以直接做快照比对（把「本周 vs 上周」变成一次 diff）。
        """
        return {
            "decisions": self.decisions,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "conflicted": self.conflicted,
            "accept_rate": round(self.accept_rate, 4),
            "by_source_card": self.by_source_card(),
            "by_target_card": self.by_target_card(),
            "by_field": self.by_field(),
        }

    # -- 内部 --

    def _distribute(self, key) -> dict[str, int]:
        """按 key 计数，**只数已裁决的记录**，输出按键排序。

        排序不是美化：无序 dict 的快照 diff 会随机抖动，而抖动的报表
        没人看。确定性是「可查数据」的前提。
        """
        out: dict[str, int] = {}
        for r in self.records:
            if r.status is DiffStatus.PENDING:
                continue
            k = key(r)
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))
