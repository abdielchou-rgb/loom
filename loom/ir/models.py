"""Narrative IR —— 三层正交模型。

    叙事编译器核心数据结构。文本只是本结构的一个「视图」(renderer)。

层级：
    L1 PlotLayer        因果情节层  —— 事件节点 + 偏序因果链 (POCL)
    L2 CharacterLayer   角色目标层  —— 每个角色的独立目标图 + 行动元绑定
    L3 CommitmentLayer  作者意图层  —— 主题断言 / 道德论证 / 硬承诺

为什么必须三层正交（Riedl & Young, IPOCL）：
    只约束 L1 -> 事件合理但角色像工具人
    只约束 L1+L2 -> 每段都合理，合起来却不证明任何东西（漂离论点）
    三层同时约束 -> 情节必然性、角色可信性、主题论证同时成立
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .base import LoomModel
from .enums import (
    ActantRole,
    ArcShape,
    ChunkOrigin,
    EntityKind,
    EnigmaState,
    Focalization,
    Frequency,
    InsertPosition,
    KeyLogic,
    Medium,
    SceneOutcome,
    Severity,
)
from .proposal import Diff, DiffStatus, resolve
from .tom import CharacterBeliefState, TensionPoint

SCHEMA_VERSION = "0.1.0"

# `LoomModel` 定义在 base.py（见该文件说明为什么必须下沉）。
# 此处重新导出，`from .models import LoomModel` 仍然可用。
#
# ⚠️ 本模块**不能**定义 `__all__`：`loom/ir/__init__.py` 用的是
# `from .models import *`，一旦加了 `__all__`，星号导入就只会带出
# `__all__` 里列的名字，`NarrativeIR` / `Storylet` / `Character` 全部静默消失。
# 这个坑踩过一次：加了 `__all__` 后「模块导入冒烟测试」仍然全绿
# （它只 import 模块、不访问属性），只有显式 `hasattr(ir, "NarrativeIR")`
# 才暴露。**导入测试不访问属性，就测不到导出面。**


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------


class TimePoint(LoomModel):
    """故事内时间点（fabula time）。"""

    day: int = Field(ge=0, description="故事内第几天")
    label: str | None = Field(default=None, description="人类可读标签，如「三年前」")
    is_flashback: bool = False


class StateDelta(LoomModel):
    """一个状态变化。Todorov 校验器的输入：场景必须至少产生一个。"""

    entity_id: str
    attribute: str
    before: Any
    after: Any
    forbidden: list[str] | None = Field(
        default=None,
        description=(
            "禁忌态（ConWriter, EMNLP 2026 的 Forbidden 三元组）。"
            "每个条目是一个 `attribute`（或 `attribute=value`）字符串，"
            "表示应用本转移**之后**，该实体不得再处于这一正向状态 —— "
            "即本转移终结了该正向状态。例：一条死亡转移的 after=\"dead\"、"
            "forbidden=[\"alive\"]，含义是应用此转移后，实体 X 不得再处于"
            "「alive」状态（不得再作为聚焦者/出场实体出现）。"
            "可选字段：旧 IR 不写 forbidden 仍能通过 extra=\"forbid\" 校验。"
        ),
    )

    @model_validator(mode="after")
    def _must_change(self) -> StateDelta:
        if self.before == self.after:
            raise ValueError(
                f"StateDelta 未产生变化 ({self.entity_id}.{self.attribute})，"
                "零增量不是状态变化"
            )
        return self


# ---------------------------------------------------------------------------
# L1 因果情节层
# ---------------------------------------------------------------------------


class Effect(LoomModel):
    """事件的效果（借 Story2Game 的 effect 分类）。"""

    kind: Literal["move", "set_attribute", "create", "remove", "reveal"]
    target: str
    attribute: str | None = None
    value: Any = None
    note: str | None = None


class Precondition(LoomModel):
    """事件的前置条件。"""

    kind: Literal["location", "inventory", "attribute", "prior_event"]
    target: str
    attribute: str | None = None
    value: Any = None
    note: str | None = None


class EventNode(LoomModel):
    """情节事件节点。2.0 可直接编译为游戏逻辑。"""

    id: str
    summary: str
    scene_id: str | None = None
    preconditions: list[Precondition] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    location: str | None = None
    surprise: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="期望违背强度 (Bae & Young 2014)。反转的量化值。",
    )


class CausalLink(LoomModel):
    """偏序因果链 (POCL)。"""

    src: str
    dst: str
    kind: Literal["enables", "causes", "prevents", "requires"]
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class PlotLayer(LoomModel):
    events: dict[str, EventNode] = Field(default_factory=dict)
    links: list[CausalLink] = Field(default_factory=list)

    def add_event(self, ev: EventNode) -> EventNode:
        if ev.id in self.events:
            raise ValueError(f"事件 id 重复: {ev.id}")
        self.events[ev.id] = ev
        return ev

    def outgoing(self, event_id: str) -> list[CausalLink]:
        return [l for l in self.links if l.src == event_id]

    def orphans(self) -> list[str]:
        """既无入边也无出边的孤立事件（首尾事件除外）。"""
        linked = {l.src for l in self.links} | {l.dst for l in self.links}
        return [eid for eid in self.events if eid not in linked]


# ---------------------------------------------------------------------------
# L2 角色目标层
# ---------------------------------------------------------------------------


class GoalNode(LoomModel):
    """角色目标图中的一个节点。冲突 = 两条目标链相撞。"""

    id: str
    description: str
    is_conscious: bool = Field(
        default=True, description="意识中的欲望(want) 还是潜意识的需求(need)"
    )
    parent: str | None = None
    achieved_at_event: str | None = None


class ActantBinding(LoomModel):
    """角色与行动元的绑定。

    同一个人物绑定多个行动元（尤其是 SUBJECT 与 OPPONENT）是反转信号，
    校验器会主动提示。
    """

    role: ActantRole
    entity_id: str
    note: str | None = None


class CharacterState(LoomModel):
    """角色在某个时间点的状态快照。"""

    at_day: int
    location: str | None = None
    condition: str = "normal"
    attributes: dict[str, Any] = Field(default_factory=dict)
    knows: list[str] = Field(
        default_factory=list, description="该角色此刻知道的信息 id（知情矩阵）"
    )


class Character(LoomModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    want: str = Field(description="外部欲望")
    need: str = Field(description="内在需求")
    flaw: str = Field(description="缺陷")
    arc_from: str
    arc_to: str
    goals: list[GoalNode] = Field(default_factory=list)
    states: list[CharacterState] = Field(default_factory=list)
    voice: str | None = Field(default=None, description="语言风格指纹")

    # --- 锚（⑦ 四卡机制）---
    # wound 是「角色受过什么伤」，lie 是「角色因此信以为真的命题」。
    # 为什么 lie 不等于 flaw：**flaw 是形容词，lie 是一个可证伪的命题。**
    # 「傲慢」无法与任何东西比对；「只要我不在乎，就不会再受伤」可以 ——
    # 它可以对着信念层（tom.py）做一致性校验，也可以在结局处检查
    # 角色是否放弃或死守了它。这是从「形容角色」到「可验证角色」的升级。
    wound: str = Field(default="", description="创伤来源（锚级真源，最高优先级）")
    lie: str = Field(
        default="",
        description="角色信以为真的命题。arc_to 的语义是「高潮时放弃或死守这个 lie」",
    )

    # --- 信念层（② ToM）---
    belief_state: CharacterBeliefState | None = Field(
        default=None,
        description="信念状态快照。为 None = 该角色未建模心智，相关校验器 SKIPPED。",
    )

    def state_at(self, day: int) -> CharacterState | None:
        applicable = [s for s in self.states if s.at_day <= day]
        return max(applicable, key=lambda s: s.at_day) if applicable else None


class CharacterLayer(LoomModel):
    characters: dict[str, Character] = Field(default_factory=dict)
    actants: list[ActantBinding] = Field(default_factory=list)

    def add(self, ch: Character) -> Character:
        if ch.id in self.characters:
            raise ValueError(f"角色 id 重复: {ch.id}")
        self.characters[ch.id] = ch
        return ch

    def goal_collisions(self) -> list[tuple[str, str, str]]:
        """粗粒度目标冲突检测：不同角色追求同一目标物。"""
        by_desc: dict[str, list[str]] = {}
        for ch in self.characters.values():
            for g in ch.goals:
                key = g.description.strip().lower()
                by_desc.setdefault(key, []).append(ch.id)
        return [
            (desc, ids[0], ids[1])
            for desc, ids in by_desc.items()
            if len(ids) > 1
        ]


# ---------------------------------------------------------------------------
# L3 作者意图 / 承诺层
# ---------------------------------------------------------------------------


class Commitment(LoomModel):
    """作者承诺 —— 必须发生的事。违反即为结构性错误。

    这是防「漂离论点」的机制。LLM 的典型失败是每段都合理、
    合起来什么都不证明；承诺层把「必须证明什么」变成硬约束。
    """

    id: str
    kind: Literal["theme", "moral_argument", "required_turn", "ending", "motif"]
    statement: str
    must_hold_at: list[str] = Field(
        default_factory=list, description="必须为真的场景 id 列表"
    )
    severity: Severity = Severity.ERROR
    #: 「这条承诺已经兑现」—— **声明式字段**，不是引擎算出来的判定。
    #:
    #: 为什么必须声明而不是计算：「主题真的兑现了没有」**不可机判**。
    #: 曾经引擎拿承诺措辞去正文里做词法匹配，实测在中文上恒假
    #: （中文无词边界，整句被切成一个 token，正文不可能逐字复现），
    #: 后果是对着正常故事 7/7 误报。判据已删除，见
    #: `validators/structure.commitment_satisfied` 的 docstring。
    #:
    #: 消费方（都是**读**，不写）：
    #:   * `validators/drift.py` —— 未标记兑现的承诺进入论点面
    #:   * `pipeline/preflight.py` —— 检查未标记兑现的承诺有没有落点
    #:   * `render/html.py` —— 报告里原样呈现「作者标记」
    satisfied: bool = False


class CommitmentLayer(LoomModel):
    premise: str = Field(description="Egri 前提：一句因果断言")
    controlling_idea: str = Field(description="McKee 控制理念")
    logline: str
    arc_shape: ArcShape
    ending_anchor: str = Field(description="结局锚点。先定终局，再反推。")
    commitments: list[Commitment] = Field(default_factory=list)

    def add(self, c: Commitment) -> Commitment:
        self.commitments.append(c)
        return c

    def unsatisfied(self) -> list[Commitment]:
        """**未被标记**为已兑现的承诺（不是「已证明未兑现」）。

        措辞要紧：`satisfied` 是声明式字段，为 False 只说明**没人声明它兑现**，
        不说明它没兑现 —— 后者不可机判。返回的是「还挂着义务的承诺」。
        """
        return [c for c in self.commitments if not c.satisfied]


# ---------------------------------------------------------------------------
# 场景层（Genette schema + 场景卡 + Todorov 状态增量）
# ---------------------------------------------------------------------------


class SceneNode(LoomModel):
    """场景节点。

    双重血统：
      Genette  —— focalizer / narrator / fabula_time / sjuzhet_index / frequency
                  白送能力：换聚焦者重写、时序算子、频率旋钮、越界视角校验
      编剧手册 —— goal / conflict / turning_point / outcome（McKee 的价值转折）
      Todorov  —— state_deltas 必须非空
    """

    id: str
    title: str

    # --- Genette ---
    focalizer: str = Field(description="谁在感知（角色 id）")
    narrator: str = Field(description="谁在讲述（角色 id 或 'narrator'）")
    focalization: Focalization = Focalization.INTERNAL
    fabula_time: TimePoint
    sjuzhet_index: int = Field(ge=0, description="话语顺序位置")
    frequency: Frequency = Frequency.SINGULATIVE

    # --- McKee 价值转折 ---
    value: str = Field(description="本场景承载的价值，如「信任」")
    value_charge_start: Literal["+", "-"]
    value_charge_end: Literal["+", "-"]

    # --- 场景卡 ---
    goal: str = Field(description="谁想要什么")
    conflict: str = Field(description="谁/什么阻碍")
    turning_point: str
    outcome: SceneOutcome
    entities: list[str] = Field(default_factory=list)
    location: str | None = None
    emotion: float = Field(default=0.0, ge=-1.0, le=1.0)

    # --- Todorov ---
    state_deltas: list[StateDelta] = Field(default_factory=list)

    # --- 产出 ---
    prose: str | None = None
    origin: ChunkOrigin = ChunkOrigin.HUMAN
    model_id: str | None = None
    prompt_version: str | None = None

    # --- ① CHANGES 自申报协议 ---
    declared: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "AI 生成正文时附带的结构化变更声明（10 类变化）。"
            "**这是提示通道，不是真值通道** —— 声明与正文/IR 矛盾时以 IR 为准。"
            "空 dict 表示模型没产出声明，属降级（校验器 SKIPPED），不是失败。"
        ),
    )
    declaration_raw: str | None = Field(
        default=None, description="声明原文，便于溯源与解析失败时的人工排查"
    )

    # --- 2.0 预留 ---
    is_branch_point: bool = False
    is_paywall_gate: bool = False
    storylet_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _value_must_flip(self) -> SceneNode:
        """McKee：场景结束时价值状态必须改变。"""
        if self.value_charge_start == self.value_charge_end:
            # 不在这里抛错——由校验器给出可读报告，避免硬失败阻塞生成
            pass
        return self

    @property
    def value_flips(self) -> bool:
        return self.value_charge_start != self.value_charge_end


# ---------------------------------------------------------------------------
# 台账层
# ---------------------------------------------------------------------------


class Enigma(LoomModel):
    """谜题台账（Barthes 阐释符码）。

    状态机：posed -> delayed -> partial -> resolved
    悬空未解 = 烂尾信号，校验器会报警。
    """

    id: str
    question: str
    planted_at_scene: str
    state: EnigmaState = EnigmaState.POSED
    revealed_to: list[str] = Field(
        default_factory=list, description="已获知的角色 id（知情矩阵）"
    )
    planned_resolution_scene: str | None = None
    resolved_at_scene: str | None = None
    device: str | None = Field(
        default=None,
        description="叙事装置标签：草蛇灰线 / 正犯 / 略犯 / 突转 / 发现",
    )
    is_foreshadow: bool = True


class KnowledgeFact(LoomModel):
    """一条「谁知道什么」的事实。用于知情矩阵校验。"""

    id: str
    content: str
    known_by: dict[str, int] = Field(
        default_factory=dict, description="角色 id -> 获知的 fabula day"
    )


# ---------------------------------------------------------------------------
# 世界 / Story Bible
# ---------------------------------------------------------------------------


class Entity(LoomModel):
    id: str
    name: str
    kind: EntityKind
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)


class Relation(LoomModel):
    """关系 —— ⑫ 有有效期的时序边。

    关系不是永久事实，是有起止的边。Loom 原先只有
    `{src, dst, kind, polarity, note}`，**没有时间维度**：
    「他们第 12 章还是朋友，第 30 章反目」无法表达，只能覆盖原关系 ——
    历史被抹掉了，而历史恰恰是关系变化类情节的唯一证据。

    `CharacterState` 早就有时间维度（`at_day` + `state_at()`），
    `Relation` 没有 —— 这是一个真实的不对称，本字段组把它补平。

    `None` 一律表示「无界」：`valid_from_day=None` = 自始如此，
    `valid_to_day=None` = 至今仍有效。两者都为 None 即原行为（永久关系），
    因此对既有 IR 完全向后兼容。
    """

    src: str
    dst: str
    kind: str
    polarity: float = Field(default=0.0, ge=-1.0, le=1.0)
    note: str | None = None
    valid_from_day: int | None = Field(
        default=None, ge=0, description="None = 自始有效"
    )
    valid_to_day: int | None = Field(default=None, ge=0, description="None = 至今有效")

    def active_at(self, day: int) -> bool:
        """该关系在第 `day` 天是否有效。两端都是闭区间。"""
        if self.valid_from_day is not None and day < self.valid_from_day:
            return False
        if self.valid_to_day is not None and day > self.valid_to_day:
            return False
        return True


class WorldRule(LoomModel):
    """世界硬规则。违反 = 设定崩坏。"""

    id: str
    statement: str
    is_hard: bool = True


class StoryBible(LoomModel):
    entities: dict[str, Entity] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)
    rules: list[WorldRule] = Field(default_factory=list)
    chronotope: str | None = Field(
        default=None, description="Bakhtin 时空体预设：road / threshold / salon ..."
    )

    def alias_index(self) -> dict[str, str]:
        idx: dict[str, str] = {}
        for e in self.entities.values():
            idx[e.name.lower()] = e.id
            for a in e.aliases:
                idx[a.lower()] = e.id
        return idx

    def relations_at(
        self, day: int, *, between: tuple[str, str] | None = None
    ) -> list[Relation]:
        """某一时点**仍然有效**的关系。

        照抄 `Character.state_at(day)` 的模式 —— 时间查询的形状应当一致，
        否则每加一个时序概念就要重新发明一次查询接口。

        `between` 传 `(a, b)` 时只取这两个人之间的关系，且**不分方向**
        （`src/dst` 是存储顺序，不是语义方向）。
        """
        out = [r for r in self.relations if r.active_at(day)]
        if between is not None:
            a, b = between
            out = [r for r in out if {r.src, r.dst} == {a, b}]
        return out


# ---------------------------------------------------------------------------
# 记忆层（lorebook，对齐工业实践字段体系）
# ---------------------------------------------------------------------------


class TimedEffect(LoomModel):
    """以「消息数」计时的时效（对齐 SillyTavern）。"""

    sticky: int = 0
    cooldown: int = 0
    delay: int = 0


class RecursionPolicy(LoomModel):
    allow_outgoing: bool = True
    prevent_further: bool = False
    delay_until_recursion: bool = False
    max_steps: int = Field(default=3, ge=0, le=10)


class LoreEntry(LoomModel):
    """一条 lore 条目。

    字段体系对齐 NovelAI Lorebook / SillyTavern World Info 的工业收敛结果。
    关键结论：关键词触发 + 预算封顶，比纯向量检索更可控（长篇里「该出现时
    没出现」是致命的，向量召回是概率性的）。
    """

    id: str
    keys: list[str]
    secondary_keys: list[str] = Field(default_factory=list)
    logic: KeyLogic = KeyLogic.AND_ANY
    content: str

    position: InsertPosition = InsertPosition.BEFORE_CHAR_DEFS
    depth: int = Field(default=4, ge=0, description="AT_DEPTH 时的深度，0 = 底部")
    role: Literal["system", "user", "assistant"] = "system"
    order: int = Field(default=100, description="越大越早处理，越不易被预算裁掉")
    token_budget: int | None = None
    reserved_tokens: float = Field(default=0.0, ge=0.0, le=1.0)
    scan_depth: int = Field(default=2000, description="扫描范围（字符数）")

    recursion: RecursionPolicy = Field(default_factory=RecursionPolicy)
    min_activations: int = 0
    inclusion_group: str | None = None
    group_weight: float = 1.0
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    timed: TimedEffect | None = None

    # CJK 必须默认关闭整词匹配，否则中文匹配全废
    match_whole_words: bool = False

    is_constant: bool = Field(default=False, description="Force Activation，永远注入")
    entity_id: str | None = None


class Lorebook(LoomModel):
    entries: dict[str, LoreEntry] = Field(default_factory=dict)

    def add(self, e: LoreEntry) -> LoreEntry:
        self.entries[e.id] = e
        return e

    def compile(
        self,
        text: str,
        budget_tokens: int = 2048,
        recent_window: str = "",
    ) -> list[LoreEntry]:
        """按工业实践的选择策略编译激活集。

        顺序：
          1. constant 条目无条件入集
          2. 关键词命中（主键 + 次键逻辑）
          3. 递归激活（命中条目再触发其它条目）
          4. 按 order 排序，按预算截断
        """
        activated: dict[str, LoreEntry] = {}
        haystack = (text + "\n" + recent_window).lower()

        def hit(e: LoreEntry) -> bool:
            if e.is_constant:
                return True
            prim = [k for k in e.keys if k.lower() in haystack]
            sec = [k for k in e.secondary_keys if k.lower() in haystack]
            if not prim:
                return False
            if not e.secondary_keys:
                return True
            match e.logic:
                case KeyLogic.AND_ANY:
                    return len(sec) >= 1
                case KeyLogic.AND_ALL:
                    return len(sec) == len(e.secondary_keys)
                case KeyLogic.NOT_ANY:
                    return len(sec) == 0
                case KeyLogic.NOT_ALL:
                    return len(sec) < len(e.secondary_keys)
            return False

        for e in self.entries.values():
            if hit(e):
                activated[e.id] = e

        # 递归激活
        for _ in range(max((e.recursion.max_steps for e in activated.values()), default=0)):
            frontier = list(activated.values())
            grew = False
            for e in frontier:
                if not e.recursion.allow_outgoing or e.recursion.prevent_further:
                    continue
                for other in self.entries.values():
                    if other.id in activated:
                        continue
                    if any(k.lower() in e.content.lower() for k in other.keys):
                        activated[other.id] = other
                        grew = True
            if not grew:
                break

        ordered = sorted(activated.values(), key=lambda e: -e.order)
        out: list[LoreEntry] = []
        used = 0
        for e in ordered:
            cost = max(1, len(e.content) // 2)  # 粗估：CJK 约 1 token / 1.5 字符
            if used + cost > budget_tokens:
                continue
            used += cost
            out.append(e)
        return out


# ---------------------------------------------------------------------------
# Storylet（2.0 运行时：超越分支）
# ---------------------------------------------------------------------------


class Condition(LoomModel):
    quality: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "not_in"]
    value: Any


class QualityEffect(LoomModel):
    quality: str
    op: Literal["set", "add", "sub"]
    value: Any


class Choice(LoomModel):
    id: str
    text: str
    effects: list[QualityEffect] = Field(default_factory=list)


class Storylet(LoomModel):
    """故事块。

    Emily Short 的三种非分支结构（Beyond Branching, 2016）：
      QBN       —— 玩家在「当前合法」的 storylet 中选
      Salience  —— 系统自动选最贴合当前情境的（本模型的 salience 字段）
      Waypoint  —— 系统向下一触发点寻路，玩家可改道（advances_waypoint 字段）

    关键性质：waypoint 反转内容经济学 —— 内容越多，故事自愈越灵敏，
    而不是下游欠债越多。
    """

    id: str
    preconditions: list[Condition] = Field(default_factory=list)
    effects: list[QualityEffect] = Field(default_factory=list)
    salience: float = Field(default=0.0, description="显著性打分")
    content: str
    choices: list[Choice] = Field(default_factory=list)

    at_waypoint: str | None = Field(
        default=None,
        description=(
            "本块挂载在哪个 waypoint 上。None = 全局可用（如兜底块）。"
            "这是骨架层与血肉层的接缝：waypoint 门控 storylet，"
            "storylet 反过来推进 waypoint。"
        ),
    )
    advances_waypoint: str | None = None
    arc_weights: dict[str, float] = Field(
        default_factory=dict,
        description="供 Director 使用的戏剧弧光权重。防止 salience 意外产出坏结局。",
    )
    patterns: list[str] = Field(
        default_factory=list,
        description="本块使用了哪些手法/母题（如「打脸」「逆袭」）。"
        "由 Director 的 EventCooldownMatrix 消费：同一手法用得过密会被降权，"
        "从而在生成侧抑制母题单调。空列表 = 不参与装置冷却。",
    )
    is_fallback: bool = Field(
        default=False,
        description="兜底块。硬不变量：永远不要给玩家零个选项，"
        "必须始终保留一张可重复触发的底牌。",
    )
    repeatable: bool = True

    def eligible(self, qualities: dict[str, Any]) -> bool:
        for c in self.preconditions:
            if c.quality not in qualities:
                return False
            actual = qualities[c.quality]
            try:
                match c.op:
                    case "==":
                        ok = actual == c.value
                    case "!=":
                        ok = actual != c.value
                    case ">":
                        ok = actual > c.value
                    case ">=":
                        ok = actual >= c.value
                    case "<":
                        ok = actual < c.value
                    case "<=":
                        ok = actual <= c.value
                    case "in":
                        ok = actual in c.value
                    case "not_in":
                        ok = actual not in c.value
                    case _:
                        ok = False
            except TypeError:
                return False
            if not ok:
                return False
        return True


# ---------------------------------------------------------------------------
# 顶层 IR
# ---------------------------------------------------------------------------


class Provenance(LoomModel):
    """溯源记录。合规必需（《微短剧发展管理办法》要求 AI 生成显著标识）。"""

    chunk_id: str
    scene_id: str | None = None
    origin: ChunkOrigin = ChunkOrigin.HUMAN
    model_id: str | None = None
    prompt_version: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    human_edit_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    char_count: int = 0


class NarrativeIR(LoomModel):
    """顶层容器。这是产品本体；文本只是它的一个渲染视图。"""

    schema_version: str = SCHEMA_VERSION
    title: str
    medium: Medium = Medium.NOVEL
    target_length: int | None = Field(default=None, description="目标字数")

    bible: StoryBible = Field(default_factory=StoryBible)
    plot: PlotLayer = Field(default_factory=PlotLayer)
    characters: CharacterLayer = Field(default_factory=CharacterLayer)
    commitment: CommitmentLayer
    scenes: list[SceneNode] = Field(default_factory=list)
    enigmas: list[Enigma] = Field(default_factory=list)
    facts: list[KnowledgeFact] = Field(default_factory=list)
    lore: Lorebook = Field(default_factory=Lorebook)
    storylets: list[Storylet] = Field(default_factory=list)
    qualities: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)

    # --- P1 动态叙事记忆（序列化形态）---
    # 记忆必须进 IR（可持久化、可重跑），否则又是一份内存态，与「IR 是
    # 产品本体」冲突。这里存**序列化后的 JSON 字符串**而不是对象本身：
    # `NarrativeMemory` 住在 `loom/pipeline/memory.py`，而本模块被它依赖，
    # 直接引用会造成 ir ↔ pipeline 的循环导入。
    memory_json: str | None = Field(
        default=None,
        description="动态叙事记忆的序列化快照（NarrativeMemory.to_json()）。",
    )

    # --- ② ToM：客观真值层 + 张力资产 ---
    objective_truth: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "客观真值层：命题 -> 真值。**这是 Loom 原先完全缺失的一层。**"
            "没有它就无法表达戏剧反讽 —— 反讽的定义就是「读者知道 X，角色以为 Y」，"
            "需要一个可比对的真值。建议由 PremiseEngine 的 ending_anchor 与 "
            "commitment 反推，不引入额外 LLM 调用。"
        ),
    )
    tension_points: list[TensionPoint] = Field(
        default_factory=list,
        description="从信念分歧派生的张力点。**生成资产，不是违规报告** —— 每条都带 suggestion。",
    )

    # --- ⑦ 提案（永不静默改写）---
    proposals: list[Diff] = Field(
        default_factory=list,
        description="结构类修订的 Diff 提案。**不自动应用**，等作者裁决。",
    )

    beat_template: str | None = None
    tags: list[str] = Field(default_factory=list)

    # -- 查询辅助 --

    def scene(self, scene_id: str) -> SceneNode | None:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def ordered_scenes(self) -> list[SceneNode]:
        """按话语顺序（sjuzhet）排序 —— 注意不是故事时间。"""
        return sorted(self.scenes, key=lambda s: s.sjuzhet_index)

    def chronological_scenes(self) -> list[SceneNode]:
        """按故事时间（fabula）排序。两者不同即为时序倒错。"""
        return sorted(self.scenes, key=lambda s: (s.fabula_time.day, s.sjuzhet_index))

    def anachronies(self) -> list[SceneNode]:
        """时序倒错场景：话语顺序与故事时间顺序不一致。"""
        sj = [s.id for s in self.ordered_scenes()]
        fb = [s.id for s in self.chronological_scenes()]
        return [self.scene(sid) for sid in sj if sj.index(sid) != fb.index(sid)]  # type: ignore[misc]

    def word_count(self) -> int:
        return sum(len(s.prose or "") for s in self.scenes)

    # -- ② ToM / ⑦ 提案 的查询辅助 --

    def top_tensions(self, n: int = 5) -> list[TensionPoint]:
        """按强度取前 n 条张力点 —— 供 TensionSeeder 喂给结构引擎。

        这是 Loom 第一个**向前看**的查询：不是「你写错了什么」，
        而是「接下来可以写什么」。
        """
        return sorted(self.tension_points, key=lambda t: -t.intensity)[:n]

    def pending_proposals(self) -> list[Diff]:
        """尚未裁决的提案。CriticLoop 产出它们，作者裁决它们。"""
        return [d for d in self.proposals if d.status is DiffStatus.PENDING]

    def accept_proposal(
        self,
        diff_id: str,
        *,
        decided_at: str | None = None,
        decided_by: str | None = None,
    ) -> Diff:
        """采纳一条结构提案 —— **这是提案生效的唯一入口**。

        `Diff.after` 在 status 变成 `accepted` 之前永远只是「提案内容」。
        没有任何代码路径会在未经本方法的情况下改写目标字段，这正是
        「永不静默改写」可以被机器检查的原因。

        状态机委托给 `proposal.resolve()`：`NarrativeIR.proposals` 是裸列表，
        而状态机只在 `ProposalSet` 之外的那一份实现里 —— 两份必然漂移。

        `decided_at` / `decided_by` 是**举证字段**（谁在何时裁的），
        透传即可；不传不影响裁决本身，只让这条记录举证力变弱。
        """
        return resolve(
            self.proposals,
            diff_id,
            DiffStatus.ACCEPTED,
            decided_at=decided_at,
            decided_by=decided_by,
        )

    def reject_proposal(
        self,
        diff_id: str,
        *,
        decided_at: str | None = None,
        decided_by: str | None = None,
    ) -> Diff:
        """拒绝一条结构提案。与 `accept_proposal` 完全对称 ——
        拒绝必须是廉价的一次性操作（Amershi et al. 2019, guideline 6）。

        **驳回是最强的人类判断证据**（见 `provenance/process.py`），
        所以这里的时间戳比 accept 那侧更需要被认真填。
        """
        return resolve(
            self.proposals,
            diff_id,
            DiffStatus.REJECTED,
            decided_at=decided_at,
            decided_by=decided_by,
        )

    def fingerprint(self) -> str:
        """IR 指纹，用于版本比对与缓存失效。"""
        payload = json.dumps(
            {
                "title": self.title,
                "scenes": [
                    {"id": s.id, "tp": s.turning_point, "out": s.outcome.value}
                    for s in self.ordered_scenes()
                ],
                "commitments": [c.statement for c in self.commitment.commitments],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, raw: str) -> NarrativeIR:
        return cls.model_validate_json(raw)
