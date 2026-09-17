"""理论心智（Theory of Mind）信念层 —— 与客观真值层比对的张力生成。

    方法论出处
    ────────────────────────────────────────────────────────────
    Premack, D. & Woodruff, G. (1978). "Does the chimpanzee have a
    theory of mind?"  *Behavioral and Brain Sciences* 1(4): 515-526.
        —— ToM 概念本身：把「他相信 P」当作可独立于「P 为真」而存在的
           心理状态来表征。本模块的 `world_beliefs` 与 `objective_truth`
           分成两个结构，就是这条区分在数据结构上的落地。

    Zunshine, L. (2006). *Why We Read Fiction: Theory of Mind and the
    Novel*. Ohio State University Press.
        —— 小说阅读即 ToM 的反复操演；读者享受的正是「我知道而角色不
           知道」的那一层落差。这为「戏剧反讽」提供了机制解释：
           反讽不是修辞技巧，是**读者心智层与角色心智层的层级差**。

    数据结构的直接来源：Æsirian `core/tom_engine/__init__.py`（686 行）的
    Belief / CharacterBeliefState / TensionType / TensionPoint，
    见 `aesirian_吸收评估.md` ②（本文档与那个仓库是本模块的设计依据）。

    为什么 Loom 原本做不到
    ────────────────────────────────────────────────────────────
    L2 角色层有 `want/need/flaw/goals/states`，而 `CharacterState.knows`
    只是一个 **id 列表** —— 没有命题、没有置信度、没有来源、没有嵌套。
    `KnowledgeFact.known_by` 只记「谁在第几天知道」，**没有真值可比**。
    于是 Loom 结构上无法表达戏剧反讽，而这是最基础的悬念机制之一。

    本模块的两个立场（与 Loom 现有 24 个校验器相反）
    ────────────────────────────────────────────────────────────
    1. **张力点是生成资产，不是违规报告。**
       现有校验器全部向后看（你写错了什么）；`TensionPoint` 向前看
       （你接下来可以写什么）。因此 `suggestion` 是**必填**字段，
       且 schema 层面拒绝空串 —— 一个只报「这里有信念冲突」而不说
       「下一场怎么用」的结构，等于把 enigma ledger 又做了一遍。
       强度先验：递归错位 0.9（最高）> 戏剧反讽 0.8（固定）>
       信念冲突（两者置信度均值）> 秘密暴露风险 0.7 > 目标冲突 0.6。
       后两个数值是本模块自定的先验，不是从文献读出来的系数。

    2. **置信度不随时间衰减。** 源项目 `advance_chapter()` 在超过 50 章后
       把 confidence ×0.95，注释写「角色会遗忘」。这是语义错误：
       读者不会遗忘，角色也不该因为章节数变多而降低对既定事实的置信度。
       它会制造虚假的 `is_erroneous` 信号。**本模块不提供任何衰减入口。**

    刻意不做的另一件事
    ────────────────────────────────────────────────────────────
    源项目的 `validate_action()` 用关键词 + 否定词启发式判定角色行动，
    并硬编码了 80+ 个 `non_character_words`（「然而」「值得注意的是」…）
    来抵消上游 NER 把副词误认成角色名的失败。**那是补丁，不是设计** ——
    该修的是实体抽取，不是在验证器里堆黑名单。本模块不含任何关键词表、
    任何黑名单、任何对行动文本的字符串匹配。

    设计说明：本模块**不定义 `__all__`**。理由见 `models.py` 顶部那条教训：
    星号导入遇到 `__all__` 会只带出清单里的名字，漏一个就静默消失。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from .base import LoomModel


# ---------------------------------------------------------------------------
# 信念
# ---------------------------------------------------------------------------


class BeliefSource(str, Enum):
    """信念的来源。

    取值用中文，因为它们是**领域词汇**（要与作者对话、要进提示词），
    不是代码里的枚举开关。源项目同此。

    后两者（欺骗 / 误解）产生的信念天生就是错的 —— `Belief` 会自动把
    `is_erroneous` 置真。这条派生必须自动，不能靠调用方记得手填：
    忘了填就会让整类错误信念在反讽检测里静默失效。
    """

    WITNESSED = "目击"
    HEARSAY = "二手信息"
    INFERENCE = "推理"
    DECEPTION = "欺骗"
    MISUNDERSTANDING = "误解"


#: 产出错误信念的来源。
_ERRONEOUS_SOURCES: frozenset[BeliefSource] = frozenset(
    {BeliefSource.DECEPTION, BeliefSource.MISUNDERSTANDING}
)


class Belief(LoomModel):
    """一个角色对一条命题的信念。

    `proposition` 是跨角色、跨真值层比对的**键**：两个角色对同一
    `proposition` 持不同 `value` 即为信念冲突；角色 `value` 与客观真值
    不同即为戏剧反讽。
    """

    proposition: str = Field(min_length=1, description="命题。跨角色/真值比对的键。")
    value: Any = Field(
        description="该角色相信这条命题的取值。与 objective_truth[proposition] 比对。"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    source: BeliefSource = Field(default=BeliefSource.INFERENCE, description="信念来源")
    updated_at: str | None = Field(
        default=None,
        description="故事内时点标签（如「第 3 章」）。**由调用方传入，本模块不取时钟** —— "
        "取 now() 的结构写不出确定性测试。",
    )
    is_erroneous: bool = Field(
        default=False,
        description="是否错误信念。来源为欺骗/误解时自动置真（见 BeliefSource）。",
    )

    @model_validator(mode="after")
    def _derive_erroneous(self) -> Belief:
        """欺骗/误解产生的信念自动标记为错误。

        守卫 `not self.is_erroneous` 是必需的：`validate_assignment=True`
        会让赋值重新触发本校验器，没有守卫就会无限递归。
        """
        if self.source in _ERRONEOUS_SOURCES and not self.is_erroneous:
            self.is_erroneous = True
        return self


# ---------------------------------------------------------------------------
# 角色信念状态（含 3 层 ToM 嵌套）
# ---------------------------------------------------------------------------


class CharacterBeliefState(LoomModel):
    """一个角色的信念状态快照。三层的容器，不是三层的数据。

    层级约定（键即身份，因此本模型不需要 character_id —— 它由外层
    `dict[角色 id, CharacterBeliefState]` 的键给出）：

        world_beliefs                     角色对客观世界的信念
        about_others[B][P]                ToM 第 1 层：A 对 B 的了解（B 在 P 上的状态）
        recursive_beliefs[B][C][P]        ToM 第 2-3 层：A 以为 B 以为 C 相信 P
                                          B == C 时即第 2 层「A 以为 B 相信 P」

    第 3 层用「信念持有者链」表达：路径上每一跳都是一次心智归因。
    这比给每层单独起一个字段名更诚实 —— 层数由路径长度决定，
    将来要支持第 4 层不需要改 schema。
    """

    world_beliefs: dict[str, Belief] = Field(
        default_factory=dict, description="命题 -> 信念。对客观世界的信念。"
    )
    about_others: dict[str, dict[str, Belief]] = Field(
        default_factory=dict,
        description="ToM 第 1 层：角色 id -> (命题 -> 信念)。A 对 B 的了解。",
    )
    recursive_beliefs: dict[str, dict[str, dict[str, Belief]]] = Field(
        default_factory=dict,
        description="ToM 第 2-3 层：持有者链 -> 命题 -> 信念。"
        "recursive_beliefs['沈砚']['沈砚']['沈砚已死'] = A 以为沈砚相信「沈砚已死」。",
    )
    known_secrets: list[str] = Field(
        default_factory=list, description="该角色自认为是秘密的命题键（须存在于真值层）"
    )
    active_goals: list[str] = Field(
        default_factory=list, description="当前活跃目标。与他人共享即目标冲突。"
    )


# ---------------------------------------------------------------------------
# 张力点（生成资产）
# ---------------------------------------------------------------------------


class TensionType(str, Enum):
    """张力类型。取值同源项目，用中文以便直接进提示词与作者界面。"""

    BELIEF_CONFLICT = "信念冲突"
    DRAMATIC_IRONY = "戏剧反讽"
    RECURSIVE_MISMATCH = "递归错位"
    SECRET_EXPOSURE_RISK = "秘密暴露风险"
    GOAL_CONFLICT = "目标冲突"


#: 强度先验。前三项取自 `aesirian_吸收评估.md` ② 的明文规定，
#: 后两项为本模块自定（不是文献系数，可整块重校准）。
INTENSITY_RECURSIVE_MISMATCH = 0.9
INTENSITY_DRAMATIC_IRONY = 0.8
INTENSITY_SECRET_EXPOSURE = 0.7
INTENSITY_GOAL_CONFLICT = 0.6


class TensionPoint(LoomModel):
    """一个可写的张力点。

    **这是生成资产，不是违规报告。** 与 `loom.validators.base.Finding`
    的区别是方向：Finding 说「你写错了什么」，TensionPoint 说
    「你接下来可以写什么」。

    `suggestion` 是必填且非空的 —— 这是本模块的立场，用 schema 强制，
    而不是靠文档劝告。缺了建议的张力点没有存在价值。
    """

    type: TensionType
    involved: list[str] = Field(
        min_length=1, description="涉及的角色 id（至少一个，否则张力无所依附）"
    )
    intensity: float = Field(ge=0.0, le=1.0, description="强度先验，用于排序与配平")
    description: str = Field(min_length=1, description="张力是什么（面向作者）")
    suggestion: str = Field(
        min_length=1,
        description="接下来写什么。**必填**：这是本结构区别于校验器的全部理由。",
    )


# ---------------------------------------------------------------------------
# 推导
# ---------------------------------------------------------------------------


def _sorted_points(points: list[TensionPoint]) -> list[TensionPoint]:
    """按强度降序 + 类型 + 涉及角色排序。

    确定性输出：同一输入必得同一顺序，消费方（TensionSeeder）不必再排一次，
    也不会因为字典迭代顺序而得到抖动的结果。
    """
    return sorted(points, key=lambda p: (-p.intensity, p.type.value, p.involved))


def find_dramatic_irony(
    states: dict[str, CharacterBeliefState],
    objective_truth: dict[str, Any],
) -> list[TensionPoint]:
    """找出戏剧反讽：读者知道真相，角色信错。

    判据只有一条：`belief.value != objective_truth[proposition]`。

    保守规则（宁可漏报，不可误报 —— 与 CSN 抽取同一立场）：
      * 命题不在真值层 → **不判定**。真值未知时「不一致」无从谈起，
        凭空报反讽会让这个指标迅速失去可信度。
      * 置信度**不参与判定**。信得再虚，错就是错；一个 0.05 置信度的
        错误信念仍然是读者与角色之间的落差。强度固定 0.8，不随置信度缩放。
    """
    out: list[TensionPoint] = []
    for cid in sorted(states):
        for prop in sorted(states[cid].world_beliefs):
            if prop not in objective_truth:
                continue
            belief = states[cid].world_beliefs[prop]
            truth = objective_truth[prop]
            if belief.value == truth:
                continue
            out.append(
                TensionPoint(
                    type=TensionType.DRAMATIC_IRONY,
                    involved=[cid],
                    intensity=INTENSITY_DRAMATIC_IRONY,
                    description=(
                        f"读者知道「{prop}」的真相是「{truth}」，"
                        f"但 {cid} 相信「{belief.value}」"
                    ),
                    suggestion=(
                        f"让 {cid} 基于这个错误认知采取行动 —— 读者会替 ta 着急；"
                        f"真相揭破时，{cid} 亲口说过的「{belief.value}」会变成回旋镖"
                    ),
                )
            )
    return out


def _belief_conflicts(
    states: dict[str, CharacterBeliefState],
) -> list[TensionPoint]:
    """信念冲突：两个角色对同一命题持不同取值。

    强度 = 两者置信度的均值 —— 双方都确信时冲突最尖锐。

    `involved` 排序输出：信念冲突是**对称**张力，谁先谁后没有语义。
    排序让同一冲突在任何调用顺序下都得到同一个列表，消费方可直接去重。
    （对比：递归错位是**非对称**的，归因者必须排在前面，故不排序。）
    """
    out: list[TensionPoint] = []
    ids = sorted(states)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            sa, sb = states[a], states[b]
            for prop in sorted(set(sa.world_beliefs) & set(sb.world_beliefs)):
                ba, bb = sa.world_beliefs[prop], sb.world_beliefs[prop]
                if ba.value == bb.value:
                    continue
                out.append(
                    TensionPoint(
                        type=TensionType.BELIEF_CONFLICT,
                        involved=sorted([a, b]),
                        # round(…, 4)：0.6+0.8 的浮点和是 1.4000000000000001，
                        # 不归整会让强度值带着二进制尾巴进遥测与快照
                        intensity=round((ba.confidence + bb.confidence) / 2, 4),
                        description=(
                            f"{a} 相信「{prop}」是「{ba.value}」，"
                            f"{b} 相信是「{bb.value}」"
                        ),
                        suggestion=(
                            f"制造一场 {a} 和 {b} 围绕「{prop}」争论的场景 —— "
                            f"双方各自都有证据，谁也无法说服谁"
                        ),
                    )
                )
    return out


def _recursive_mismatches(
    states: dict[str, CharacterBeliefState],
) -> list[TensionPoint]:
    """递归错位：A 对 B 心智的建模，与 B 的实际信念不符。

    判据包含「B 根本不知道」这一情形 —— 那正是误会喜剧的引擎：
    A 以为 B 已经知情，于是行事坦荡；B 一无所知，于是一头雾水。

    `subject` 不在 `states` 里时**不判定**：那个角色没有信念状态可比对，
    报出来的只是「未登记」，不是张力。
    """
    out: list[TensionPoint] = []
    for a in sorted(states):
        layers = states[a].recursive_beliefs
        for holder in sorted(layers):
            for subject in sorted(layers[holder]):
                other = states.get(subject)
                if other is None:
                    continue
                for prop in sorted(layers[holder][subject]):
                    assumed = layers[holder][subject][prop]
                    actual = other.world_beliefs.get(prop)
                    if actual is not None and actual.value == assumed.value:
                        continue
                    actual_desc = (
                        "没有任何信念（不知道）"
                        if actual is None
                        else f"相信「{actual.value}」"
                    )
                    out.append(
                        TensionPoint(
                            type=TensionType.RECURSIVE_MISMATCH,
                            involved=[a, subject],
                            intensity=INTENSITY_RECURSIVE_MISMATCH,
                            description=(
                                f"{a} 以为 {subject} 相信「{prop}」是「{assumed.value}」，"
                                f"但 {subject} 实际上{actual_desc}"
                            ),
                            suggestion=(
                                f"让 {a} 按「{subject} 已经知道 {prop}」这个前提行动，"
                                f"而 {subject} 其实不知道 —— 误会即将穿帮，"
                                f"那一场就是本卷的转折点"
                            ),
                        )
                    )
    return out


def _secret_exposure_risks(
    states: dict[str, CharacterBeliefState],
    objective_truth: dict[str, Any],
) -> list[TensionPoint]:
    """秘密暴露风险：A 以为是秘密，别人已经知情或起疑。

    两条独立路径，任一命中即成立：
      1. 别人 `world_beliefs` 里已有该命题且**取值与真值相同** —— 已经知道；
      2. 别人 `about_others[A]` 里出现了该命题 —— ToM 第 1 层上的**起疑**
         （哪怕对方还没把怀疑上升为信念，风险也已经存在）。

    同一对（持有人, 知情者）无论命中几条路径都只报一条 —— 重复计数会
    让「秘密暴露风险」这个指标失真。秘密不在真值层时保守跳过。
    """
    out: list[TensionPoint] = []
    for holder in sorted(states):
        for secret in sorted(set(states[holder].known_secrets)):
            if secret not in objective_truth:
                continue
            truth = objective_truth[secret]
            suspects: set[str] = set()
            for other in sorted(states):
                if other == holder:
                    continue
                known = states[other].world_beliefs.get(secret)
                if known is not None and known.value == truth:
                    suspects.add(other)
                    continue
                if secret in states[other].about_others.get(holder, {}):
                    suspects.add(other)
            if not suspects:
                continue
            who = "、".join(sorted(suspects))
            out.append(
                TensionPoint(
                    type=TensionType.SECRET_EXPOSURE_RISK,
                    involved=[holder, *sorted(suspects)],
                    intensity=INTENSITY_SECRET_EXPOSURE,
                    description=(
                        f"{holder} 把「{secret}」当作秘密，"
                        f"但 {who} 已经知情或起疑"
                    ),
                    suggestion=(
                        f"安排一场 {who} 无意间露出破绽的场景，"
                        f"让 {holder} 意识到秘密正在失守 —— 之后 {holder} 的每一步"
                        f"都会带着「会不会被看穿」的第二层动机"
                    ),
                )
            )
    return out


def _goal_conflicts(
    states: dict[str, CharacterBeliefState],
) -> list[TensionPoint]:
    """目标冲突：两个角色追同一个目标。

    注意与 `CharacterLayer.goal_collisions()` 的分工：那里比的是
    `GoalNode.description`（目标图上的节点），这里比的是信念层上的
    `active_goals`（当前活跃目标）。前者是结构，后者是此刻。
    """
    out: list[TensionPoint] = []
    ids = sorted(states)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            shared = sorted(set(states[a].active_goals) & set(states[b].active_goals))
            for goal in shared:
                out.append(
                    TensionPoint(
                        type=TensionType.GOAL_CONFLICT,
                        involved=sorted([a, b]),
                        intensity=INTENSITY_GOAL_CONFLICT,
                        description=f"{a} 与 {b} 都想「{goal}」",
                        suggestion=(
                            f"让 {a} 与 {b} 为「{goal}」正面相撞：同一目标只能有一个人拿到，"
                            f"先到的人得利、后到的人失去的不只是目标"
                        ),
                    )
                )
    return out


def derive_tension_points(
    states: dict[str, CharacterBeliefState],
    objective_truth: dict[str, Any],
) -> list[TensionPoint]:
    """从一组角色信念状态 + 客观真值层派生全部张力点。

    参数
    ----
    states
        角色 id -> 该角色的信念状态。角色 id 就是 `involved` 里出现的名字。
    objective_truth
        命题 -> 客观真值。**这是 Loom 原本缺失的那一层**：没有它，
        角色信什么都无从判定对错，戏剧反讽结构上不可表达。
        建议由 `CommitmentLayer.ending_anchor` 与 `commitments` 反推，
        而不是额外加一次 LLM 调用。

    返回按强度降序排好的张力点列表。空输入返回空列表（不抛异常）——
    张力是可选的生成辅助，缺数据时应该安静地不产出，而不是打断流水线。
    """
    points: list[TensionPoint] = []
    points.extend(find_dramatic_irony(states, objective_truth))
    points.extend(_belief_conflicts(states))
    points.extend(_recursive_mismatches(states))
    points.extend(_secret_exposure_risks(states, objective_truth))
    points.extend(_goal_conflicts(states))
    return _sorted_points(points)
