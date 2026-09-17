"""自主运行前的**计划**门禁（preflight）。

**它守的是哪一道门（为什么它值得存在）：**
自主模式（`loom run`）让机器自己一场一场往下写，直到某个由 IR 派生的停止条件
被满足。自主性会**放大初始计划的质量**：一行想法 → 前提 → 结局锚点，
这条链上的每一个弱点都会被忠实且大规模地执行 —— 产出的每一场单独看都合理，
合起来什么都不证明。**那正是本项目存在的理由**，所以在开跑之前先卡计划，
而不是等跑完十万字再体检。

**与既有校验器的分工（不读这一段会被当成重复实现）：**

    ┌─────────────────────┬──────────────────┬────────────────┬────────────┐
    │                     │ 运行时机          │ 输入形态        │ 卡的是谁    │
    ├─────────────────────┼──────────────────┼────────────────┼────────────┤
    │ commitment_satisfied│ 生成之后          │ 已有场景的 IR   │ 成品        │
    │ premise_fidelity    │ 生成之后（看结局）│ 有正文/多场      │ 成品        │
    │ drift_guard         │ 跑动中（尾窗口径）│ 已有 ≥4 场       │ 过程        │
    │ **preflight**       │ **生成之前**      │ **通常 0 场**   │ **计划**    │
    └─────────────────────┴──────────────────┴────────────────┴────────────┘

三条具体差别：

1. **不看场景。** 本模块**一个字段都不读 `ir.scenes`** —— 计划阶段通常还没有
   场景。这既是「与成品校验器不同」的定义，也是它不会在空场景列表上崩的原因。
2. **不查 `must_hold_at` 指向的场景是否存在。** `commitment_satisfied` 会报
   「承诺指向的场景不存在」，那在生成**之后**是真缺陷；在生成**之前**它恒为真
   （场景还没生成），报出来只是必然的噪音。本模块只要求 `must_hold_at`
   **非空** —— 有落点才有可派生的停止条件。
3. **判据是「有没有」，不是「对不对」。** 成品校验器判质量（价值翻转、谜题回收）；
   本模块只判计划里有没有那几样**后续一切机制的依赖项**：没有结局锚点就没有
   目的地，没有未兑现承诺就没有可派生的停止条件，没有控制理念就连漂移都无从度量。

**每条判据的出处（无出处即不发货，铁律 3）：**

    ending_anchor     项目自述的设计原则 + Egri
                      * `loom/llm/prompts.py::PREMISE` system：
                        「结局锚点必须具体到动作或画面，不是情绪描述」，
                        且该提示词要求「先确定结局锚点与关键转折，再反推主题」。
                      * Egri《The Art of Dramatic Writing》(1946)：前提是戏的脊骨，
                        必须**被结局证明**（demonstrated），不是被提及。
                        ⇒ 没有可指认的动作/画面，就没有可供证明的东西。
    premise           `loom/llm/prompts.py::PREMISE` system 明文：
                        「前提（premise）必须是一句因果断言，不是主题词。
                        反例：「关于信任」。正例：「偏执地独自承担一切，
                        会把最该信任的人推成敌人。」」+ Egri 同上（前提 = 因果断言）。
    commitment        Riedl & Young, IPOCL（见 `loom/ir/models.py` 模块 docstring）：
                        L3 作者承诺层把「必须证明什么」变成硬约束，
                        是防「漂离论点」的机制 —— 无承诺层即无机制。
                        `Commitment.must_hold_at` 是承诺与场景顺序的接缝
                        （`structure.py::commitment_satisfied` 就是靠它定位的），
                        停止条件也只能从这条缝派生。
    controlling_idea  McKee《Story》(1997) controlling idea（价值 + 原因）。
                        `loom/validators/drift.py` 的 `thesis_drift` 把
                        `controlling_idea` 当基线来比；字段为空 ⇒ 下游漂移
                        门禁连基线都没有（"有数据、没判据"的反向缺口）。
    character_need    Truby《The Anatomy of Story》(2007)：want 与 need 的落差
                        是人物弧光的引擎；项目自述同旨 ——
                        `loom/llm/prompts.py::CHARACTERS` system：
                        「want（外部欲望）与 need（内在需求）必须不同 ——
                        这个落差就是人物弧光的引擎」。

**严重度语义：**
阻断项（`blockers`，ERROR）= 计划缺了某一项后续机制的**依赖项**，开跑必然空转。
警告项（`warnings`，WARN）= 计划可跑，但作者应当知道少一样东西。
`character_need` 是唯一的警告项，理由见该函数的 docstring。

**局限（铁律 7：不宣称做不到的事）：**

1. **全部是词表/标点层面的代理判据，没有句法分析，更没有语义理解。**
   它测不出「前提写得很长但其实是空话」，也测不出「锚点有动作但这个动作
   与主题无关」。它能测的只有一件事：计划里**有没有**那几样东西，以及
   它们是不是**退化成了主题词 / 纯情绪词**这两种最常见的退化形态。
2. **判据只在这种退化的极端处开口**（整条前提没有任何因果标记且没有分句；
   整个锚点除了情绪词什么都不剩）。这是本项目的一贯纪律
   （见 `drift.py`：「只在零重叠处开口，不用编出来的阈值」）——
   宁可漏报，不可误报；误报会让作者学会忽略这道门。
3. 因此**通过 preflight 只说明计划不缺依赖项，不说明计划是好的。**
   它不由任何方式度量创意质量。

**刻意不做的事：**
* 不调用 `loom.validators.base.register()` —— 它不是「故事体检报告」的一行，
  它是一道**能否开跑**的开关；且注册表与 `REQUIRES` 表属集成方串行编辑的范围，
  本模块不碰。
* 不读正文（`prose`）—— 文本是渲染视图，不是真值（铁律 1）。
* 不修改 IR 任何一个字段（与「永不静默改写」一致）。

用法：
    >>> result = preflight(ir)
    >>> if not result.ok:
    ...     for f in result.blockers:
    ...         print(f.render())
    >>> assert_ready(ir)   # 有阻断项时抛 PreflightError
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ir.enums import Severity
from ..ir.models import NarrativeIR
from ..validators.base import Finding

#: 所有 Finding 的 code。刻意统一成一个：本模块是一道门，不是一个校验器矩阵，
#: 具体是哪一条由 `evidence["check"]` 区分，见 `CHECK_IDS`。
CODE = "preflight"

#: 本模块实现的检查项。`preflight` 恒等于跑完全部项（没有数据依赖型跳过 ——
#: 计划阶段的「数据缺失」本身就是结论，不是「没测」），故 `checks_run` 恒为此长度。
CHECK_IDS: tuple[str, ...] = (
    "ending_anchor",
    "premise",
    "commitment",
    "controlling_idea",
    "character_need",
)


class PreflightError(RuntimeError):
    """计划未通过 preflight。阻断项与修改建议已写进异常消息。"""


@dataclass
class PreflightResult:
    ok: bool
    blockers: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    checks_run: int = 0

    def render(self) -> str:
        head = "✓ 计划可以开跑" if self.ok else f"✗ 计划被 {len(self.blockers)} 项阻断"
        lines = [f"── preflight ── {head}（跑过 {self.checks_run} 项检查）"]
        for f in self.blockers:
            lines.append(f.render())
        for f in self.warnings:
            lines.append(f.render())
        if not self.blockers and not self.warnings:
            lines.append("  （无阻断项、无警告）")
        return "\n".join(lines)


def _f(
    check: str,
    severity: Severity,
    message: str,
    suggestion: str,
    **evidence: object,
) -> Finding:
    return Finding(
        code=CODE,
        severity=severity,
        message=message,
        suggestion=suggestion,
        evidence={"check": check, **evidence},
    )


# ---------------------------------------------------------------------------
# 1. 结局锚点：非空，且具体到动作或画面
# ---------------------------------------------------------------------------

#: 情绪 / 抽象状态词表（封闭类）。
#:
#: 用途只有一个：判断锚点**除了这类词之外还剩不剩别的东西**。它**不**用来判断
#: 「这个词是不是情绪」—— 那需要语义，本模块没有。故判据是「全部命中且不剩
#: 任何内容词」，不是「含有一个情绪词」：后者会把「他把刀留在雪地里，然后
#: 释然」这种合格锚点也拦下来。
# ⚠️ **不许有重复项。** 词表是「摘掉命中项后还剩不剩内容」的判据，
# 重复项本身无害，但会让「删掉某一项」这类变异测不出来 —— 变异存活一旦
# 发生，就无法再声称这条判据被测试覆盖了。去重由 `test_preflight` 断言。
_EMOTION_TERMS: tuple[str, ...] = (
    "悲伤", "悲痛", "痛苦", "疼", "释然", "释怀", "和解", "成长", "救赎",
    "孤独", "寂寞", "寂寥", "落寞", "孤单", "幸福", "快乐", "遗憾", "后悔",
    "懊悔", "愤怒", "愤恨", "恐惧", "害怕", "爱", "恨", "平静", "安宁",
    "坦然", "空虚", "麻木", "冷漠", "迷茫", "迷惘", "顿悟", "觉醒", "醒悟",
    "自由", "意义", "希望", "绝望", "失望", "宽恕", "原谅", "尊严", "耻辱",
    "温暖", "温柔", "哀伤", "怅然", "宁静", "满足", "执念", "完满", "圆满",
    "沉静", "安然",
)

#: 英文同表（同一用途）。
_EN_EMOTION: frozenset[str] = frozenset(
    {
        "sadness", "grief", "pain", "healing", "growth", "redemption",
        "loneliness", "happiness", "regret", "anger", "fear", "love", "hate",
        "calm", "peace", "emptiness", "awakening", "freedom", "meaning",
        "hope", "despair", "relief", "forgiveness", "acceptance", "closure",
    }
)

#: 功能词 / 副词 / 标点：剥离后剩下的才是「内容」。
#: 只剥虚词，不剥动词 —— 「他终于释然」剥掉「终于」「他」后应剩下「释然」，
#: 而「他终于把刀留在雪地里」应剩下「把刀留在雪地」，后者还有内容 → 放行。
_FUNCTION_TOKENS: tuple[str, ...] = (
    "最终", "最后", "终于", "后来", "从此", "永远", "一切", "全部", "完全",
    "深深", "渐渐", "一个", "一种", "一场", "一次", "所有", "什么", "自己",
    "的", "了", "着", "地", "得", "与", "和", "及", "或", "在", "是", "也",
    "都", "就", "才", "却", "还", "而", "其", "对", "把", "被", "让", "使",
    "，", "。", "；", "：", "、", "！", "？", "…", "—", "～", "\n", "\t",
    "「", "」", "『", "』", "《", "》", "（", "）", "(", ")", "“", "”", '"',
    "他", "她", "它", "你", "我",
)

_EN_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "his", "her", "their", "he", "she",
        "they", "then", "finally", "with", "to", "of", "in", "on", "at",
        "is", "was", "has", "have", "will", "into", "for",
    }
)

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _strip_to_content(text: str) -> tuple[str, list[str], bool]:
    """把锚点剥成「内容」。

    返回 `(剩余汉字, 英文内容词, 是否命中过情绪词)`：
      * 逐条摘掉情绪词（命中即记 `hit=True`）
      * 再摘掉功能词与标点
      * 剩下任何汉字，或任何非停用词的英文词，都算「还有动作或画面」
    """
    rest = text
    hit = False
    for term in _EMOTION_TERMS:
        if term in rest:
            hit = True
            rest = rest.replace(term, " ")
    for tok in _FUNCTION_TOKENS:
        rest = rest.replace(tok, " ")
    cjk_left = "".join(_CJK.findall(rest))

    lowered = text.lower()
    latin = [w for w in re.split(r"[^a-z]+", lowered) if len(w) > 1]
    hit = hit or any(w in _EN_EMOTION for w in latin)
    latin_content = [
        w for w in latin if w not in _EN_EMOTION and w not in _EN_STOPWORDS
    ]
    return cjk_left, latin_content, hit


def _check_ending_anchor(ir: NarrativeIR) -> list[Finding]:
    """结局锚点必须存在，且具体到动作或画面，不是情绪描述。

    出处：`loom/llm/prompts.py::PREMISE`（明文要求「具体到动作或画面，
    不是情绪描述」，且要求「先确定结局锚点与关键转折，再反推主题」）+
    Egri 1946（前提必须被结局**证明**）。

    为什么是阻断项：自主运行没有目的地就会一直写到别的条件（预算 / 长度）
    来停它 —— 那不是「写完了」，是「被叫停了」，二者产出的东西完全不同。

    判据（只在极端处开口）：
      * 空               → 阻断（没有目的地）
      * 除情绪/抽象词外什么都不剩 → 阻断（是情绪描述，不是动作或画面）
      * 连一个可识别的内容词都没有 → 阻断（同上，且更彻底）

    局限：以「内心」「灵魂」这类未被词表覆盖的抽象名词承载的情绪描述会漏过。
    这是词表法的已知盲区，按本项目的取舍（宁漏报不误报）接受。
    """
    anchor = (getattr(ir.commitment, "ending_anchor", "") or "").strip()
    if not anchor:
        return [
            _f(
                "ending_anchor",
                Severity.ERROR,
                "结局锚点为空 —— 自主运行没有目的地，会一直写到预算耗尽为止",
                "先定终局再开跑：写一句**具体的动作或画面**"
                "（如「他把刀留在雪地里，转身走进风雪」），而不是主题或情绪",
                ending_anchor="",
                reason="empty",
            )
        ]

    cjk_left, latin_content, hit_emotion = _strip_to_content(anchor)
    if cjk_left or latin_content:
        return []

    if hit_emotion:
        return [
            _f(
                "ending_anchor",
                Severity.ERROR,
                f"结局锚点「{anchor}」是纯情绪/抽象描述，没有任何动作或画面",
                "把情绪换成可以被拍出来的一件事：谁做了什么、留下了什么、"
                "站在哪里。情绪是那件事的结果，不是那件事本身",
                ending_anchor=anchor,
                reason="emotion_only",
            )
        ]
    return [
        _f(
            "ending_anchor",
            Severity.ERROR,
            f"结局锚点「{anchor}」里识别不出任何动作或画面成分",
            "写成一个可指认的场景瞬间（动作 + 对象 + 地点），"
            "而不是一个词或一个概念",
            ending_anchor=anchor,
            reason="no_content",
        )
    ]


# ---------------------------------------------------------------------------
# 2. 前提：一句因果断言，不是主题词
# ---------------------------------------------------------------------------

#: 汉语因果 / 转折 / 结果标记词表。
#:
#: 这是「因果断言」的**操作化定义**，不是语法解析。选词依据是提示词自己给出的
#: 正例「偏执地独自承担一切，**会**把最该信任的人**推成**敌人」里承担因果的
#: 那几个成分，加上汉语里承担同类功能的常用连词与结果补语标记。
_CAUSAL_MARKERS: tuple[str, ...] = (
    "因为", "所以", "因此", "因而", "由于", "于是", "从而", "致使", "导致",
    "以致", "以至于", "结果", "最终", "最后", "终将", "必将", "总会", "只会",
    "就会", "才会", "能把", "会把", "会让", "会使", "使得", "让", "使",
    "越", "反而", "却", "然而", "但是", "但", "换来", "付出", "代价",
    "变成", "成为", "推成", "推向", "沦为", "走向", "失去", "赢得", "毁了",
    "救了", "害了", "逼成", "逼向",
)

#: 英文同表（同一用途）。
_EN_CAUSAL_MARKERS: frozenset[str] = frozenset(
    {
        "because", "so", "therefore", "thus", "hence", "leads", "lead",
        "causes", "cause", "destroys", "destroy", "turns", "turn", "becomes",
        "become", "until", "unless", "costs", "cost", "destroys", "pushes",
        "into", "when", "if", "then", "ends", "leaves", "wins", "loses",
    }
)

#: 分句标点（不含句末句号 —— 句末句号不证明「有两个分句」）。
_CLAUSE_PUNCT: tuple[str, ...] = ("，", ",", "；", ";", "：", ":", "、")

#: 主题词形态：`loom/llm/prompts.py` 点名的反例就是「关于信任」。
_TOPIC_PREFIXES: tuple[str, ...] = ("关于", "有关", "一个关于", "这是关于")
_EN_TOPIC_PREFIXES: tuple[str, ...] = ("about", "a story about", "the theme of")


def _check_premise(ir: NarrativeIR) -> list[Finding]:
    """前提必须是一句因果断言，不是主题词。

    出处：`loom/llm/prompts.py::PREMISE` system 明文 ——
    「前提（premise）必须是一句因果断言，不是主题词。反例：「关于信任」。
    正例：「偏执地独自承担一切，会把最该信任的人推成敌人。」」
    + Egri 1946（前提是可被证明的因果命题，不是题材）。

    为什么是阻断项：主题词不产生可判定的方向。「关于信任」开跑后，任何一场
    都可以自称在讲信任 —— 这就是「每段都合理、合起来什么都不证明」的入口。

    判据（三条，都是提示词自己给出的形态，没有编阈值）：
      1. 空                              → 阻断
      2. 「关于…」/ "about …" 形态        → 阻断（提示词点名的反例本身）
      3. 既无因果标记、又无分句           → 阻断（是一个词/短语，不是断言）

    局限：词表法，测不出「写得很长但其实是空话」，也测不出同义改写。
    它只能拦住主题词这种**最普遍的退化形态**。
    """
    premise = (getattr(ir.commitment, "premise", "") or "").strip()
    if not premise:
        return [
            _f(
                "premise",
                Severity.ERROR,
                "前提为空 —— 整个运行没有要证明的命题",
                "写一句因果断言：「什么样的行为/性格，会导致什么样的结果」。"
                "反例是主题词「关于信任」，正例是「偏执地独自承担一切，"
                "会把最该信任的人推成敌人」",
                premise="",
                reason="empty",
            )
        ]

    lowered = premise.lower()
    for p in _TOPIC_PREFIXES:
        if premise.startswith(p):
            return [
                _f(
                    "premise",
                    Severity.ERROR,
                    f"前提「{premise}」是主题词形态（以「{p}」开头），不是因果断言",
                    "前提要能被证明 —— 把它改写成「X 导致 Y」："
                    "什么样的行为，会把什么样的结果带出来",
                    premise=premise,
                    reason="topic_marker",
                    marker=p,
                )
            ]
    for p in _EN_TOPIC_PREFIXES:
        if lowered.startswith(p):
            return [
                _f(
                    "premise",
                    Severity.ERROR,
                    f"前提「{premise}」是主题词形态（以 “{p}” 开头），不是因果断言",
                    "Rewrite as a causal assertion: “X leads to Y” — "
                    "what behaviour produces what consequence",
                    premise=premise,
                    reason="topic_marker",
                    marker=p,
                )
            ]

    has_marker = any(m in premise for m in _CAUSAL_MARKERS) or any(
        m in re.split(r"[^a-z]+", lowered) for m in _EN_CAUSAL_MARKERS
    )
    has_clause = any(p in premise for p in _CLAUSE_PUNCT)
    if not has_marker and not has_clause:
        return [
            _f(
                "premise",
                Severity.ERROR,
                f"前提「{premise}」没有因果标记也没有分句 —— 它是一个词/短语，不是断言",
                "补上因果：谁做了什么，于是发生了什么。"
                "正例形态是「偏执地独自承担一切，会把最该信任的人推成敌人」",
                premise=premise,
                reason="no_causal_marker",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 3. 承诺层：至少一条未兑现且带落点的承诺
# ---------------------------------------------------------------------------


def _check_commitment(ir: NarrativeIR) -> list[Finding]:
    """至少一条**未兑现**且 `must_hold_at` 非空的承诺。

    出处：Riedl & Young, IPOCL（见 `loom/ir/models.py`：L3 承诺层是防
    「漂离论点」的机制，把「必须证明什么」变成硬约束）+ 项目自主模式的设计
    （停止条件由**尚未兑现**的承诺派生 —— 兑现完了即到站）。

    为什么是阻断项，而且是**最硬**的一条：这两样东西缺一样，自主运行就
    **没有可派生的停止条件**。停止条件不是「写够了 N 场」，而是
    「该兑现的都兑现了」；没有未兑现的承诺，机器只能靠预算停下。

    注意（与 `commitment_satisfied` 的分界）：**本模块不检查 `must_hold_at`
    指向的场景是否存在。** 生成之前场景本来就不存在，那条判据在计划阶段
    恒为真，报出来只是必然的噪音；它属于成品校验器。
    """
    commitments = list(getattr(ir.commitment, "commitments", None) or [])
    if not commitments:
        return [
            _f(
                "commitment",
                Severity.ERROR,
                "承诺层为空 —— 没有可派生的停止条件，自主运行只能靠预算停下",
                "至少加一条 theme 承诺和一条 ending 承诺"
                "（提示词 `premise` 也是这么要求的），并为它们填上 must_hold_at",
                reason="empty",
                commitments=0,
            )
        ]

    unsatisfied = [c for c in commitments if not getattr(c, "satisfied", False)]
    if not unsatisfied:
        return [
            _f(
                "commitment",
                Severity.ERROR,
                f"全部 {len(commitments)} 条承诺都已兑现 —— 运行没有剩余义务，"
                "停止条件在第 0 场就已满足",
                "计划已经完成，不需要自主运行；若要继续写，先补新的承诺",
                reason="all_satisfied",
                commitments=len(commitments),
            )
        ]

    anchored = [
        c for c in unsatisfied if list(getattr(c, "must_hold_at", None) or [])
    ]
    if not anchored:
        return [
            _f(
                "commitment",
                Severity.ERROR,
                f"{len(unsatisfied)} 条未兑现承诺没有一条带 must_hold_at —— "
                "承诺没有落点，停止条件无从派生",
                "给未兑现的承诺填上 must_hold_at（它必须为真的一场或多场），"
                "这是承诺层与场景顺序之间唯一的接缝",
                reason="no_anchor",
                unsatisfied=len(unsatisfied),
                commitments=len(commitments),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 4. 控制理念
# ---------------------------------------------------------------------------


def _check_controlling_idea(ir: NarrativeIR) -> list[Finding]:
    """控制理念非空 —— 没有它，下游连漂移都无从度量。

    出处：McKee《Story》(1997) controlling idea（价值 + 原因）。
    `loom/validators/drift.py::thesis_drift` 拿 `controlling_idea` 当基线，
    逐段比对尾窗是否还碰论点；同一份文件里写过一句本模块认同的话：
    「`ir.commitment.controlling_idea` 这个字段就是按它命名的 —— 本模块只是
    终于有了一个会读它的校验器（这正是本项目反复出现的「有数据、没判据」型
    缺口）」。字段为空 ⇒ 那条门禁连基线都没有，整个漂移防线在开跑前就是瞎的。
    """
    idea = (getattr(ir.commitment, "controlling_idea", "") or "").strip()
    if not idea:
        return [
            _f(
                "controlling_idea",
                Severity.ERROR,
                "控制理念为空 —— 自主运行期间无法度量漂移（没有可比对的基线）",
                "填一句「价值 + 原因」：这个故事最终证明了什么，"
                "以及是因为什么（如「真正的背叛不是被出卖，而是从未允许别人靠近」）",
                reason="empty",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 5. 角色需求（Truby）—— 唯一的警告项
# ---------------------------------------------------------------------------


def _check_character_need(ir: NarrativeIR) -> list[Finding]:
    """至少一个角色有 `need`（内在需求）—— 警告，不阻断。

    出处：Truby《The Anatomy of Story》(2007) —— want 与 need 的落差是
    人物弧光的引擎；项目自述同旨，`loom/llm/prompts.py::CHARACTERS` system：
    「want（外部欲望）与 need（内在需求）必须不同 —— 这个落差就是人物弧光的引擎」。

    **为什么是 WARN 而不是阻断项（这一条必须写清楚，否则就是在虚报门禁）：**
    本模块区分不了两种状态 ——
      (a) 角色**还没设计**（`CharacterEngine` 在场景骨架之后才跑，计划阶段空表是正常的）
      (b) 角色**设计过了但没有 need**（真缺陷）
    二者在本检查看来完全一样。拿一个分不清的状态去阻断运行，就是让作者为
    「还没到那一步」付代价；那会迅速教会作者关掉这道门。故只警告。

    局限：只看 `need` 字段是否非空，**不判断 want 与 need 是否真的不同**
    （那是 `desire_need_conflict` 的活，且它同样需要两个字段都在）。
    """
    characters = dict(getattr(ir.characters, "characters", None) or {})
    named = [c for c in characters.values() if (getattr(c, "need", "") or "").strip()]
    if not named:
        return [
            _f(
                "character_need",
                Severity.WARN,
                f"没有任何角色填写了 need（内在需求）（共 {len(characters)} 个角色）—— "
                "缺少 want/need 落差，人物弧光没有引擎",
                "若角色层还没设计，可先开跑，CharacterEngine 会补；"
                "若已设计，给主角填上 need —— 它必须与 want 不同（Truby）",
                reason="no_need",
                characters=len(characters),
            )
        ]
    return []


# ---------------------------------------------------------------------------


_CHECKS = (
    _check_ending_anchor,
    _check_premise,
    _check_commitment,
    _check_controlling_idea,
    _check_character_need,
)


def preflight(ir: NarrativeIR) -> PreflightResult:
    """跑全部计划检查。**不抛异常、不改 IR。**

    缺失的数据一律以阻断项/警告的形式回来，不变成异常 —— 计划阶段的
    「数据缺失」本身就是结论（见模块 docstring：判据是「有没有」，不是「对不对」）。

    `checks_run` 恒为 `len(CHECKS)`：本模块没有数据依赖型跳过，
    因为「没有数据」在这里正是要报告的结论，把它记成「没测」是虚报。
    """
    blockers: list[Finding] = []
    warnings: list[Finding] = []
    for fn in _CHECKS:
        for finding in fn(ir):
            if finding.severity is Severity.ERROR:
                blockers.append(finding)
            else:
                warnings.append(finding)
    return PreflightResult(
        ok=not blockers,
        blockers=blockers,
        warnings=warnings,
        checks_run=len(_CHECKS),
    )


def assert_ready(ir: NarrativeIR) -> None:
    """有阻断项就抛 `PreflightError`，否则静默返回。

    警告项**不**触发异常 —— 允许开跑，但调用方应当把 `warnings` 转达给作者。
    异常消息直接复用 `Finding.render()`，因此它自带 suggestion。
    """
    result = preflight(ir)
    if result.ok:
        return None
    lines = [
        f"计划未通过 preflight：{len(result.blockers)} 项阻断"
        f"（共跑 {result.checks_run} 项检查）"
    ]
    for f in result.blockers:
        lines.append(f.render())
    raise PreflightError("\n".join(lines))
