"""校验器框架。

设计原则：校验器只产出 Finding，不抛异常、不阻断生成。
「故事体检报告」是产品本体的一部分，不是事后补的营销功能
（Wardrip-Fruin《Expressive Processing》：永远不要隐藏模型的推理）。

── 关于四态（2026-09-14 补）────────────────────────────────────

**SKIPPED ≠ PASS，CRASHED 两者都不是。** 这个区分不是洁癖，是防止系统骗自己。

原实现里，校验器拿不到数据时返回 `[]`，与「检查通过」在返回值上完全不可区分。
后果：「所有校验器全过」这句话可能只是「大部分校验器没数据可查」——
一个看起来很好、实际什么都没测的指标。

现在分成四态：
    PASS     跑过了，没问题
    FAIL     跑过了，有 Finding
    SKIPPED  数据不足，**没跑**，不参与健康分
    CRASHED  跑了，但**校验器自己崩了** —— 记进 `Report.crashes`

CRASHED 是 2026-09-14 补的第三种失败。它抓到的真实缺陷：
`pattern_saturation` 把 `SceneNode.storylet_ids` 写成了 `Storylet.storylet_ids`，
在没有 storylet 的 IR 上完全正常（生成器表达式体不求值），
在有 storylet 的 IR 上抛 AttributeError。**「干净基线全绿」与「这个分支
从来没跑过」同时成立** —— 只有让崩溃变成一个会被断言的显式状态才抓得到。

需求是**声明式**的（`REQUIRES`），不写在校验器函数里。理由：
  1. 校验器函数一行都不用改
  2. 需求表可以被测试断言（每个注册的 code 必须有声明，否则测试失败）——
     这防的是「注册了却永远不会被真正执行」的死校验器
  3. 需求表本身就是文档：一眼看出哪些校验器依赖哪些数据

出处：Æsirian 的 `STRUCTURAL_GATE_REQUIREMENTS` 与「SKIP 不等同 PASS」原则
（他们修过 23 道「registry 有、dispatcher 无」的死门禁，代价是写了一个静态
解析源码的测试来抓。声明式需求表 + 断言测试是更省事的做法）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..ir.enums import ChunkOrigin, Medium, Severity
from ..ir.models import NarrativeIR


@dataclass
class Finding:
    """一条体检结论。"""

    code: str
    severity: Severity
    message: str
    scene_id: str | None = None
    entity_id: str | None = None
    suggestion: str | None = None
    evidence: dict = field(default_factory=dict)

    def render(self) -> str:
        loc = f" [{self.scene_id or self.entity_id}]" if (self.scene_id or self.entity_id) else ""
        head = {Severity.ERROR: "✗", Severity.WARN: "!", Severity.INFO: "·"}[self.severity]
        line = f"  {head} {self.code}{loc}: {self.message}"
        if self.suggestion:
            line += f"\n      → {self.suggestion}"
        return line


ValidatorFn = Callable[[NarrativeIR], list[Finding]]

_REGISTRY: dict[str, ValidatorFn] = {}


def register(code: str) -> Callable[[ValidatorFn], ValidatorFn]:
    def deco(fn: ValidatorFn) -> ValidatorFn:
        _REGISTRY[code] = fn
        return fn

    return deco


def get_validator(code: str) -> ValidatorFn | None:
    return _REGISTRY.get(code)


def available() -> list[str]:
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# 数据需求（声明式）
# ---------------------------------------------------------------------------

#: 具名能力探针：IR 是否具备某种数据
NEEDS: dict[str, Callable[[NarrativeIR], bool]] = {
    "scenes>=1": lambda ir: len(ir.scenes) >= 1,
    "scenes>=2": lambda ir: len(ir.scenes) >= 2,
    "scenes>=3": lambda ir: len(ir.scenes) >= 3,
    "commitments": lambda ir: bool(ir.commitment.commitments),
    "enigmas": lambda ir: bool(ir.enigmas),
    "facts": lambda ir: bool(ir.facts),
    "actants": lambda ir: bool(ir.characters.actants),
    "plot_events": lambda ir: bool(ir.plot.events),
    "named_entities": lambda ir: bool(ir.bible.entities)
    or bool(ir.characters.characters),
    "world_rules": lambda ir: bool(ir.bible.rules),
    "beat_template": lambda ir: ir.beat_template is not None,
    "medium:micro_drama": lambda ir: ir.medium is Medium.MICRO_DRAMA,
    "any_prose": lambda ir: any(s.prose for s in ir.scenes),
    "any_ai_origin": lambda ir: any(
        s.origin is not ChunkOrigin.HUMAN for s in ir.scenes
    ),
    # -- 合规向检测器（keel/validators/compliance.py）--
    "dialogue": lambda ir: any(
        s.prose and any(m in s.prose for m in ("「", "『", "“", '"'))
        for s in ir.scenes
    ),
    # -- ①②⑦⑫ 新增数据层 --
    # 前提：Egri 因果断言。没有它，「有没有偏离前提」无从判断。
    "premise": lambda ir: bool((ir.commitment.premise or "").strip()),
    "declarations": lambda ir: any(s.declared for s in ir.scenes),
    # Truby：角色有没有「需求」这个字段（与 want 区分开）。
    "needs": lambda ir: any(
        (c.need or "").strip() for c in ir.characters.characters.values()
    ),
    # Fan 分层：场景是否声明了可供比对的**结构**（转折点 / 冲突）。
    "declared_structure": lambda ir: any(
        (s.turning_point or "").strip() or (s.conflict or "").strip()
        for s in ir.scenes
    ),
    "lies": lambda ir: any(
        (c.lie or "").strip() for c in ir.characters.characters.values()
    ),
    # Truby 四元：欲望与需求**同时存在**才是可评估的 —— 缺一个就只能 SKIPPED。
    "desire_need": lambda ir: any(
        (c.want or "").strip() and (c.need or "").strip()
        for c in ir.characters.characters.values()
    ),
    "beliefs": lambda ir: any(
        c.belief_state is not None for c in ir.characters.characters.values()
    ),
    "objective_truth": lambda ir: bool(ir.objective_truth),
    "secrets": lambda ir: any(
        c.belief_state is not None and c.belief_state.known_secrets
        for c in ir.characters.characters.values()
    ),
    "relations": lambda ir: bool(ir.bible.relations),
    # P6 互动叙事分支一致性：IR 上是否有分支结构。
    "branches": lambda ir: bool(getattr(ir, "branches", None)),
}

#: 校验器 code -> 必需的数据探针。不在表里的视为「永远可评估」。
REQUIRES: dict[str, tuple[str, ...]] = {
    # -- structure --
    "value_charge_flip": ("scenes>=1",),
    "state_delta": ("scenes>=1",),
    "commitment_satisfied": ("commitments", "scenes>=1"),
    "enigma_resolution": ("enigmas",),
    "mirror_bookends": ("scenes>=2",),
    "emotion_curve_match": ("scenes>=3",),
    "li_yu_main_brain": ("commitments", "scenes>=2"),
    "li_yu_reduce_threads": ("scenes>=2",),
    "mao_repeat_variation": ("scenes>=2",),
    "actant_collision": ("actants",),
    "focalizer_boundary": ("scenes>=1",),
    "causal_chain_integrity": ("plot_events",),
    "hook_cadence": ("medium:micro_drama", "scenes>=1"),
    "paywall_gate_present": ("medium:micro_drama", "scenes>=1"),
    "template_coverage": ("beat_template",),
    "thread_budget": ("scenes>=1",),
    "mice_thread_closure": ("scenes>=3",),
    "narrative_arc_shape": ("scenes>=3",),
    # Truby 下半：需求在高潮兑现。高潮段要有 3 场以上才谈得上「高潮」。
    "need_revelation_at_climax": ("needs", "scenes>=3"),
    # Fan 分层生成：正文 vs 该场声明的结构。需要正文，且需要结构声明非空。
    "prose_structure_fidelity": ("any_prose", "declared_structure"),
    "outcome_distribution": ("scenes>=1",),
    # P2 显式状态转移语义：ConWriter (EMNLP 2026) Pre/Post/Forbidden 符号化验证。
    # 需要 ≥2 场才能跨场追问「禁忌态是否被后续场景复现」。
    "state_transition_integrity": ("scenes>=2",),
    # P6 互动叙事分支一致性：两条分支对同一实体设互斥状态 → ERROR。
    "branch_consistency": ("branches",),
    # 前提忠实度：没有前提就无从判断「有没有偏离前提」—— SKIPPED，不是 PASS。
    "premise_fidelity": ("premise",),
    # -- consistency --
    "knowledge_matrix": ("enigmas",),
    "revelation_regression": ("enigmas",),
    "timeline_monotonic": ("scenes>=2",),
    "entity_reference": ("scenes>=1",),
    "alias_collision": ("named_entities",),
    "world_rule_violation": ("world_rules",),
    "provenance_coverage": ("scenes>=1",),
    "numeric_fact_consistency": ("any_prose", "named_entities", "scenes>=2"),
    # -- narrative（①②⑦⑫）--
    "pattern_saturation": ("scenes>=2",),
    "declaration_consistency": ("declarations",),
    # 欲望/需求：Truby 四元。两个字段都有才谈得上「它们是否冲突」。
    "desire_need_conflict": ("desire_need",),
    "lie_arc_closure": ("lies", "scenes>=2"),
    "belief_consistency": ("beliefs", "objective_truth"),
    "dramatic_irony_available": ("beliefs", "objective_truth"),
    "secret_reveal_ordering": ("secrets", "objective_truth"),
    "relation_temporal": ("relations",),
    # 全局漂移：需要**足够长的样本**才有「尾窗」可言（3 场以下无从判断趋势），
    # 且必须有控制理念可比 —— 没有论点就谈不上「偏离论点」，那应当是
    # SKIPPED 而不是 PASS（铁律 10）。
    "drift_guard": ("scenes>=3", "commitments"),
    # -- compliance（平台合规向，见 compliance.py 的模块 docstring）--
    "length_burstiness": ("any_prose",),
    "adverb_density": ("any_prose",),
    "dialogue_rhythm": ("dialogue",),
}

#: 显式声明「不依赖任何可选数据、永远可评估」的校验器。
#: 与 REQUIRES 二选一，测试会断言每个注册 code 必须落在这两者之一。
ALWAYS_EVALUABLE: frozenset[str] = frozenset()

#: 设计上只做通报、**不可能**产出 WARN/ERROR 的函数。
#:
#: 它们仍然注册（体检报告里要出现），但**不是门禁项**：
#: 健康分不受它们影响，所以把它们算进「N 个校验器」是在虚报覆盖能力。
#: 这正是 Æsirian 那 167 道门禁的问题 —— 数量好看，但其中相当一部分
#: 永远不会让任何作品不通过。
#:
#: 分类不是人工判断，是**可机检的事实**：`scripts/verify.py` 会扫描这些
#: 函数的源码，断言里面不出现 `Severity.WARN` / `Severity.ERROR`。
#: 谁哪天把它改成会报警，测试立刻失败，逼着它离开这份名单。
REPORTS: frozenset[str] = frozenset(
    {
        "mirror_bookends",  # 首尾同形：可能是刻意回到原点，通报即可
        "revelation_regression",  # 单场景信息密度：创作口味问题
        "thread_budget",  # 纯统计：价值线分布
        # ② 反讽点：Keel 第一个**向前看**的检查 —— 它不说「你写错了什么」，
        # 它说「你接下来可以写什么」。永远只输出 INFO。
        # 若把它当门禁会立刻产生荒谬语义：故事「可用反讽点太少」= 不健康。
        # 可用的张力点多寡与作品好坏没有单调关系，故它是报表项。
        "dramatic_irony_available",
        # -- 平台合规向（compliance.py）--
        # 这三个报的是「平台的统计画像与你的文本吻合程度」，不是结构缺陷。
        # 判据来源是平台公开风控口径，会随平台改口径而变；判为门禁会让
        # 「平台今天怎么想」变成「故事能不能过」的一部分 —— 那是把外部
        # 政策的变动直接接进产品质量分，属于接错了线。
        "length_burstiness",
        "adverb_density",
        "dialogue_rhythm",
        # -- 两个新读数项（分类理由见 ADVISORY_READOUT）--
        "mice_thread_closure",
        "narrative_arc_shape",
    }
)

#: 产出**非结构信号**的校验器 code：它们的 Finding 走 `Report.advisory` 通道，
#: 出现在报告里但**不进健康分**。
#:
#: 与 `REPORTS` 是两个不同的轴，别混：
#:   * `REPORTS`  = 「不可能产出 WARN/ERROR」→ 不是门禁（判据可机检：扫源码）
#:   * `ADVISORY` = 「产出的是非结构信号」→ 不进 `score()`（判据可机检：看通道）
#: 一个函数可以同时属于两者，也可以只属于其中一个。
#:
#: 为什么需要这条通道（本次会话实测）：
#:   `dramatic_irony_available` 是「向前看」的报表 —— 它说的是「你接下来可以
#:   写什么」。它输出的每条 INFO 都会按 `score()` 的公式扣 1 分。于是
#:   **一个故事可写的张力越多，健康分越低** —— 一个无法解释的头条指标。
#:   TensionSeeder 一接入基线，基线分数就会因「多了一些可写的好东西」而下降。
#:
#: 不变的边界（沿用作者既有偏好）：`CriticLoop` 仍然只**自动**修文风类；
#: 结构类问题现在升级为「生成 Diff 提案供一键采纳」，但仍不自动应用。
ADVISORY: frozenset[str] = frozenset(
    {
        "dramatic_irony_available",
        # 三个合规向检测器：它们报的是**缺陷**（文本落在平台的机器区间），
        # 不是机会。见 `ADVISORY_DEFECT`。
        "length_burstiness",
        "adverb_density",
        "dialogue_rhythm",
        # 三个老报表项（原先只在 REPORTS 里，INFO 仍每条扣 1 分）。
        # 分类见 ADVISORY_DEFECT / ADVISORY_READOUT —— **不要**顺手全塞进
        # 缺陷型：`thread_budget` 是读数不是缺陷，塞进去会逼出一个假反例。
        "mirror_bookends",
        "revelation_regression",
        "thread_budget",
        # 两个新读数项（见 ADVISORY_READOUT 的说明）：测量，不是缺陷。
        "mice_thread_closure",
        "narrative_arc_shape",
    }
)

#: `ADVISORY` 里的**缺陷型**项：沉默在干净输入上是**正确结果**，不是空转。
#:
#: 这个区分是被逼出来的，不是分类癖。advisory 通道原先只有一项
#: `dramatic_irony_available`，它是**机会型**的 —— 「你接下来可以写什么」。
#: 对机会型项，「在一个正常故事上一条都不产出」是故障：可写的张力点多寡
#: 与作品好坏无关，永远沉默等于不存在。故 `verify.py` 断言它必须在基线上说话。
#:
#: 缺陷型项恰好相反：干净稿子上**应当**一条都不出。若把同一条断言套上去，
#: 就会逼着合规检测器对着干净稿子硬报 —— 为了让指标好看而制造假阳性，
#: 正是这份文件反复警告的「给自己的指标注水」。
#:
#: 所以缺陷型项的**非空转**由它自己的反例变异证明，不由基线证明：
#:   * 缺陷型（ADVISORY_DEFECT）→ 必须在**它自己的反例**上产出
#:   * 其余（机会型 + 读数型）  → 必须在**基线**上产出
#:
#: 判据可机检（两个方向都断言）：`ADVISORY_DEFECT ⊆ ADVISORY`，
#: 且每个缺陷型项都必须在 `tests/fixtures.MUTATIONS` 里有反例。
ADVISORY_DEFECT: frozenset[str] = frozenset(
    {
        "length_burstiness",
        "adverb_density",
        "dialogue_rhythm",
        # 两个老报表项：它们都是**条件触发**的真缺陷 ——
        #   mirror_bookends        首尾状态完全同形（净变化为零）
        #   revelation_regression  单场景承载 >3 条谜题动作
        # 干净稿子上**应当**沉默，且两者都有现成反例，故属缺陷型。
        "mirror_bookends",
        "revelation_regression",
    }
)

#: `ADVISORY` 里的**读数型**项：它是**测量**，不是判断 —— 永远产出一条。
#:
#: 这个区分同样是被逼出来的。把老报表项迁进 ADVISORY 时，`thread_budget`
#: 归不进任何一类：
#:   * 它不是**机会型**（`dramatic_irony_available` 那种「你接下来可以写什么」）
#:   * 它也不是**缺陷型** —— 干净稿子上它**必须**说话，因为它只是在报
#:     「价值线分布：X×3，Y×2（共 N 条）」。给它编一个反例，
#:     等于为了让分类整齐而制造一个不存在的故障。
#:
#: 更关键的是：**它原先扣的那 1 分毫无信息。** 它无条件产出，
#: 于是每篇作品的基线都被同一个常数压低 1 分 ——
#: 这不是「结构变差了」，是「我们多装了一个读数」。
#:
#: 非空转判据：读数型必须在**基线**上产出（与机会型同一条断言，理由不同：
#: 机会型是「永远沉默等于不存在」，读数型是「永远说话是它的定义」）。
ADVISORY_READOUT: frozenset[str] = frozenset(
    {
        "thread_budget",
        # MICE 线程开合视图：报「开了几类线、收了几类」。
        # 未闭合本身已由各专门门禁报错，这里只做**类型层面的测量**，
        # 再造一个门禁会让同一件事被罚两次分。
        "mice_thread_closure",
        # 故事形状：只报 staging / progression 两个测量值，
        # **不套用 Toubia 的回归系数做成功预测**（无校准数据，铁律 7）。
        "narrative_arc_shape",
    }
)


def unmet_needs(ir: NarrativeIR, code: str) -> list[str]:
    """返回该校验器在当前 IR 上缺失的数据项；空列表表示可评估。"""
    missing: list[str] = []
    for need in REQUIRES.get(code, ()):
        probe = NEEDS.get(need)
        if probe is None:
            missing.append(f"未知需求 {need!r}")
        elif not probe(ir):
            missing.append(need)
    return missing


def registry_stats() -> dict:
    """registry 的机器可读统计。

    **文档里的校验器数量必须从这里取，不许手写。**
    （反面教材：本次会话中 README 与方案文档都写「16 个校验器」，实际 24 个。
    手写的数字必然漂移，因为它没有任何机制与代码同步。）

    `total` 包含报表项；对外宣称「N 个校验器」时必须用 `gating` ——
    报表项永远不会让作品不通过，算进门禁数量是虚报。
    """
    by_module: dict[str, int] = {}
    for fn in _REGISTRY.values():
        mod = (fn.__module__ or "?").rsplit(".", 1)[-1]
        by_module[mod] = by_module.get(mod, 0) + 1
    declared = sum(1 for c in _REGISTRY if c in REQUIRES)
    reports = sorted(set(REPORTS) & set(_REGISTRY))
    return {
        "total": len(_REGISTRY),
        "gating": len(_REGISTRY) - len(reports),
        "reports": len(reports),
        "report_codes": reports,
        "with_declared_requirements": declared,
        "always_evaluable": len(_REGISTRY) - declared,
        "by_module": dict(sorted(by_module.items())),
    }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    #: code -> 跳过原因（缺失的数据项）。**不参与健康分。**
    skipped: dict[str, list[str]] = field(default_factory=dict)
    #: code -> 异常摘要。**校验器自己崩了。**
    #:
    #: 这是第四种状态，和 PASS / FAIL / SKIPPED 都不同：
    #:   PASS     跑过了，没问题
    #:   FAIL     跑过了，有 Finding
    #:   SKIPPED  数据不足，没跑
    #:   CRASHED  跑了，但**它自己出错了** —— 既没有结论，也不是「没问题」
    #:
    #: 为什么必须单列（本次会话实测）：原实现把异常包成一条 INFO Finding
    #: 塞进报告。后果有两层：
    #:   1. **一个代码 bug 会扣故事的分数。** 校验器崩了是 Keel 的缺陷，
    #:      不是这个故事的缺陷 —— 让作者为我们的 bug 付健康分是错的。
    #:   2. **它读起来像一条普通发现。** `structure.py::pattern_saturation`
    #:      把 `SceneNode.storylet_ids` 写成了 `Storylet.storylet_ids`，
    #:      在没有 storylet 的 IR 上完全正常（生成器表达式不求值），
    #:      在有 storylet 的 IR 上抛 AttributeError —— 于是「干净基线全绿」
    #:      和「这个分支从来没跑过」同时成立，漂了很久没人发现。
    #:      现在 `scripts/verify.py` 断言 `crashes` 在所有输入上为空，
    #:      崩了就红。
    crashes: dict[str, str] = field(default_factory=dict)
    #: 只通报、**不进健康分**的项。用于非结构性信号（工艺 / 文风 / 可读性 / 认知负荷）。
    #:
    #: 为什么必须单列：`score()` 的名字是「**结构**健康分」，而工艺信号不是结构缺陷。
    #: 两者共用一个数字会产生一个无法解释的头条指标 —— 加 4 个检测器就会
    #: 无声地把分数往下推，读者分不清是「结构变差了」还是「多装了 4 个检查」。
    #: （实测：craft 6 条 INFO 让干净基线 95→89。）
    advisory: list[Finding] = field(default_factory=list)

    def add(self, *fs: Finding) -> None:
        self.findings.extend(fs)

    def add_advisory(self, *fs: Finding) -> None:
        """加**只通报**的发现：出现在报告里，但不参与 `score()` 与 `passed()`。

        与 SKIPPED 的区别：SKIPPED 是「没测」，advisory 是「测了，但它不是结构问题」。
        两者都不进健康分，理由不同。
        """
        self.advisory.extend(fs)

    def skip(self, code: str, missing: list[str]) -> None:
        self.skipped[code] = missing

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARN]

    @property
    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.INFO]

    @property
    def evaluated(self) -> list[str]:
        """真正跑过、且有结论的校验器 code。崩溃的与跳过的都不算。"""
        return sorted(set(_REGISTRY) - set(self.skipped) - set(self.crashes))

    def coverage(self, total: int | None = None) -> float:
        """评估覆盖率 = 有结论的 / 总数。**这是体检报告必须一起报的数字。**

        只报「健康分 92」而不报覆盖率，等于隐瞒了「有多少项根本没测」。
        SKIPPED（没跑）与 CRASHED（跑了但崩了）都**不计入**分子 ——
        两者都没有结论，把任何一个算成「测过了」都是虚报。
        """
        n = total if total is not None else len(_REGISTRY)
        if not n:
            return 0.0
        return (n - len(self.skipped) - len(self.crashes)) / n

    def score(self) -> int:
        """0-100 结构健康分。ERROR 扣 12，WARN 扣 4，INFO 扣 1。

        SKIPPED 不扣分 —— 没测不等于测出问题。
        """
        return max(0, 100 - 12 * len(self.errors) - 4 * len(self.warnings) - len(self.infos))

    def passed(self) -> bool:
        return not self.errors

    def render(self, title: str = "故事体检报告", show_skipped: bool = True) -> str:
        lines = [f"── {title} " + "─" * max(0, 46 - len(title))]
        if not self.findings:
            lines.append("  ✓ 未发现问题")
        else:
            # 严重度降序：ERROR 在前
            for f in sorted(
                self.findings, key=lambda x: -list(Severity).index(x.severity)
            ):
                lines.append(f.render())
        lines.append("─" * 56)
        cov = self.coverage()
        lines.append(
            f"  健康分 {self.score()}/100   "
            f"错误 {len(self.errors)} · 警告 {len(self.warnings)} · 提示 {len(self.infos)}"
        )
        lines.append(
            f"  评估覆盖 {cov:.0%}"
            f"（跑过 {len(_REGISTRY) - len(self.skipped) - len(self.crashes)}"
            f"/{len(_REGISTRY)} · 跳过 {len(self.skipped)}"
            f" · 崩溃 {len(self.crashes)}）"
        )
        if self.crashes:
            # 崩溃要**喊出来**，不能像普通发现那样混在列表里 ——
            # 它意味着这份报告是不完整的，而不是这份稿子有问题。
            lines.append("")
            lines.append(
                f"  ⚠ 有 {len(self.crashes)} 个校验器自身出错 —— "
                "本报告不完整（这是 Keel 的缺陷，不是稿子的缺陷）"
            )
            for code, err in sorted(self.crashes.items()):
                lines.append(f"      {code}: {err}")
        if show_skipped and self.skipped:
            # 按缺失原因聚类，比逐个列 code 更有信息量
            by_reason: dict[str, list[str]] = {}
            for code, missing in sorted(self.skipped.items()):
                by_reason.setdefault("+".join(missing), []).append(code)
            for reason, codes in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
                lines.append(f"    ⊘ 缺 {reason}：{len(codes)} 个 — {', '.join(codes)}")

        if self.advisory:
            lines.append("")
            lines.append(
                f"── 非结构信号（{len(self.advisory)} 项，**不计入健康分**）"
                + "─" * 20
            )
            lines.append(
                "  这些不是结构缺陷：文本工艺（AI 味 / 张力 / 风格 / 传输度 / 认知负荷）"
            )
            lines.append(
                "  与「向前看的张力点」（接下来可以写什么）。它们与结构分共用一个数字"
            )
            lines.append(
                "  会让头条指标无法解释 —— 加几个检测器分数就降，或可写的张力越多"
            )
            lines.append("  分数越低 —— 故单列。")
            for f in sorted(
                self.advisory, key=lambda x: -list(Severity).index(x.severity)
            ):
                lines.append(f.render())
        return "\n".join(lines)


def run_all(ir: NarrativeIR, only: list[str] | None = None) -> Report:
    """跑全部（或指定）校验器。

    数据不足的校验器被标记为 SKIPPED，而不是静默返回空。
    `ADVISORY` 名单里的 code 的产出走 advisory 通道（不进健康分）。
    """
    codes = only if only is not None else available()
    report = Report()
    for code in codes:
        fn = _REGISTRY.get(code)
        if fn is None:
            continue
        missing = unmet_needs(ir, code)
        if missing:
            report.skip(code, missing)
            continue
        try:
            found = fn(ir)
            if code in ADVISORY:
                report.add_advisory(*found)
            else:
                report.add(*found)
        except Exception as exc:
            # 校验器自身出错：记进 `crashes`，**不产出 Finding**。
            # 两条理由（见 Report.crashes 的说明）：
            #   1. 代码 bug 不该扣稿子的健康分；
            #   2. 混成一条普通 INFO 会让它读起来像一条创作发现，
            #      于是「崩溃」与「发现问题」在报告上不可区分。
            report.crashes[code] = repr(exc)
    return report


def coverage_report(ir: NarrativeIR) -> dict:
    """当前 IR 上各校验器的可评估性（不执行，只看数据够不够）。

    用途：接真模型前先看「这份 IR 能让多少校验器真正工作」——
    避免出现「全过」但实际什么都没测的假绿。
    """
    rows: list[dict] = []
    for code in available():
        missing = unmet_needs(ir, code)
        rows.append({"code": code, "evaluable": not missing, "missing": missing})
    evaluable = sum(1 for r in rows if r["evaluable"])
    return {
        "total": len(rows),
        "evaluable": evaluable,
        "skipped": len(rows) - evaluable,
        "coverage": evaluable / len(rows) if rows else 0.0,
        "rows": rows,
    }
