"""流水线引擎：Idea -> IR 的各个阶段。

    PremiseEngine    想法 -> L3 作者承诺层
    CastEngine       承诺 -> 卡司表（解开 structure <-> characters 的循环）
    StructureEngine  承诺 + 模板 -> L1 情节层 + 场景骨架
    CharacterEngine  承诺 -> L2 角色层 + 世界层（含锚：wound / lie）
    LoreSeeder       世界层 -> 记忆层（lorebook）
    LedgerSeeder     场景 -> 悬念台账 + 知情矩阵
    TensionSeeder    信念层 + 真值层 -> **张力点**（Loom 第一个「向前看」的引擎）
    Scripter         场景卡 -> 正文（注入 lore，剥离 CHANGES 自申报）
    Proposer         结构类问题 -> Diff 提案（**不自动应用**）
    CriticLoop       体检 -> 修订（只自动修文风类；结构类转提案）

设计约束（来自 v2 调研）：
  - **生成与修订必须是两个独立阶段**（Re3）。混在一起会让模型自我确认。
  - **Critic 应当可以用不同模型**。同模型自评倾向于给高分。
  - **控制点越靠上游越好**（DOC）。所以人在回路的确认点设在 IR 层，不在文本层。
  - **向前看与向后看是两种能力。** 校验器向后看（你写错了什么），
    `TensionSeeder` 向前看（你接下来可以写什么）。后者产出的是**生成资产**，
    因此它的每条产出都必须带 `suggestion` —— 只报「这里有张力」而不说
    「下一场怎么用」，等于把 enigma ledger 又做了一遍。
"""

from __future__ import annotations

import time

from dataclasses import dataclass, field
from typing import Any

from ..audit.anti_slop import scan_ir, scan_slop, slop_findings
from ..ir.arcs import ARC_DESCRIPTIONS
from ..ir.medium_craft import craft_brief, length_hint
from ..llm.declaration import split
from ..ir.enums import (
    ActantRole,
    ArcShape,
    EntityKind,
    Focalization,
    Frequency,
    KeyLogic,
    Medium,
    SceneOutcome,
    Severity,
)
from ..ir.models import (
    ActantBinding,
    CausalLink,
    Character,
    CharacterLayer,
    CharacterState,
    Commitment,
    CommitmentLayer,
    Condition,
    Diff,
    Effect,
    Entity,
    Enigma,
    EnigmaState,
    EventNode,
    GoalNode,
    KnowledgeFact,
    Lorebook,
    LoreEntry,
    NarrativeIR,
    PlotLayer,
    Precondition,
    QualityEffect,
    RecursionPolicy,
    Relation,
    SceneNode,
    StateDelta,
    StoryBible,
    Storylet,
    TimePoint,
    WorldRule,
)
from ..ir.templates import BeatTemplate, get_template
from ..ir.tom import (
    Belief,
    BeliefSource,
    CharacterBeliefState,
    TensionPoint,
    derive_tension_points,
)
from ..llm.base import Generator
from ..provenance.awareness import awareness_block
from ..validators import available, run_all
from .repair import RepairBudget, detect_conflicts, mark_conflicted

# ---------------------------------------------------------------------------
# Stage 1：内核层
# ---------------------------------------------------------------------------


@dataclass
class PremiseEngine:
    gen: Generator

    def run(
        self,
        idea: str,
        *,
        medium: Medium = Medium.NOVEL,
        arc_shape: ArcShape = ArcShape.MAN_IN_A_HOLE,
        template_id: str = "save_the_cat",
        target_length: int = 180000,
    ) -> CommitmentLayer:
        tpl = get_template(template_id)
        from ..llm.prompts import describe_beats

        out = self.gen.generate(
            "premise",
            {
                "idea": idea,
                "medium": medium.value,
                "target_length": target_length,
                "arc_shape": arc_shape.value,
                "template_name": tpl.name,
                "beat_names": "、".join(b.name for b in tpl.beats),
            },
        )

        commitments = [
            Commitment(
                id="cm_theme",
                kind="theme",
                statement=out.get("theme_statement", ""),
                severity=Severity.ERROR,
                must_hold_at=[],
            ),
            Commitment(
                id="cm_ending",
                kind="ending",
                statement=out.get("ending_anchor", ""),
                severity=Severity.ERROR,
                must_hold_at=[],
            ),
            Commitment(
                id="cm_moral",
                kind="moral_argument",
                statement=out.get("moral_argument", ""),
                severity=Severity.WARN,
                must_hold_at=[],
            ),
        ]
        for i, turn in enumerate(out.get("required_turns", []) or []):
            commitments.append(
                Commitment(
                    id=f"cm_turn_{i + 1}",
                    kind="required_turn",
                    statement=str(turn),
                    severity=Severity.ERROR,
                    must_hold_at=[],
                )
            )

        return CommitmentLayer(
            premise=out.get("premise", idea),
            controlling_idea=out.get("controlling_idea", ""),
            logline=out.get("logline", idea),
            arc_shape=arc_shape,
            ending_anchor=out.get("ending_anchor", ""),
            commitments=commitments,
        )


# ---------------------------------------------------------------------------
# Stage 1.5：卡司表
# ---------------------------------------------------------------------------


@dataclass
class CastEngine:
    """卡司表：从前提抽出「谁在这部戏里」。

    为什么单独成一步（而不是直接进角色层）：
      结构层需要先知道「有几个人、谁跟谁对撞」才能排场次；
      但完整的角色层（欲望 / 需求 / 弧光 / 语言风格）要等场景排完才能定，
      否则角色是为一个还不存在的故事写的。

    两者拆开后循环依赖消失，顺序变成严格线性：
      premise -> cast -> structure -> characters(带场景) -> ...
    """

    gen: Generator

    def run(self, commitment: CommitmentLayer) -> list[dict[str, str]]:
        out = self.gen.generate(
            "characters",
            {
                "premise": commitment.premise,
                "controlling_idea": commitment.controlling_idea,
                "moral_argument": next(
                    (c.statement for c in commitment.commitments
                     if c.kind == "moral_argument"),
                    "",
                ),
                "scenes": [],
                "depth": "roster",  # 提示词可用：只要 id/name/功能位
            },
        )
        roster: list[dict[str, str]] = []
        for rc in out.get("characters", []) or []:
            cid = str(rc.get("id") or rc.get("name") or "").strip()
            if not cid:
                continue
            roster.append(
                {
                    "id": cid,
                    "name": str(rc.get("name", cid)),
                    "want": str(rc.get("want", "")),
                    "need": str(rc.get("need", "")),
                }
            )
        return roster


# ---------------------------------------------------------------------------
# Stage 2：结构层
# ---------------------------------------------------------------------------


@dataclass
class StructureEngine:
    gen: Generator

    def run(
        self,
        commitment: CommitmentLayer,
        characters: list[str],
        *,
        names: dict[str, str] | None = None,
        template_id: str = "save_the_cat",
        scene_count: int = 5,
    ) -> tuple[PlotLayer, list[SceneNode]]:
        """生成情节层与场景骨架。

        `characters` 是角色 **id**（IR 内部一律用 id，机器友好）；
        `names` 是 id -> 显示名的映射。场景卡里的 goal / conflict 是要给人
        和给模型读的自然语言，必须用显示名 —— 否则正文里会冒出
        「他要的是 protagonist 想要的东西」这种把内部标识漏进文本的事故。
        这个 id/名字的边界是架构必须显式守住的，不能指望下游自觉。

        弧线从 `commitment.arc_shape` 取 —— 承诺层已经持有它，不必再传参。
        必须传进 payload：**不告诉模型声明了哪条弧线，却要求它填 emotion，
        然后拿一个校验器去判断它填得对不对**，这个要求在信息上不可能被满足。
        """
        tpl: BeatTemplate = get_template(template_id)
        from ..llm.prompts import describe_beats

        arc = commitment.arc_shape
        out = self.gen.generate(
            "structure",
            {
                "template_name": tpl.name,
                "beats": describe_beats(tpl),
                "beat_list": [
                    {"id": b.id, "name": b.name, "purpose": b.purpose}
                    for b in tpl.beats
                ],
                "premise": commitment.premise,
                "ending_anchor": commitment.ending_anchor,
                "required_turns": [c.statement for c in commitment.commitments
                                   if c.kind == "required_turn"],
                "characters": characters,
                "character_ids": characters,
                "character_names": names or {},
                "scene_count": scene_count,
                "arc_shape": arc.value,
                "arc_description": ARC_DESCRIPTIONS[arc],
            },
        )

        raw_scenes = out.get("scenes") or out.get("items") or []
        plot = PlotLayer()
        scenes: list[SceneNode] = []
        nmap = dict(names or {})

        def humanize(text: Any) -> str:
            """把文本里残留的内部 id 换回显示名。

            真实模型有时会把 payload 里的 id 直接抄进自然语言字段。
            与其在提示词里求它别这么做，不如在这里兜一道 ——
            提示词是软的，代码是硬的。
            """
            s = str(text or "")
            for cid, cname in sorted(nmap.items(), key=lambda kv: -len(kv[0])):
                if cid and cid != cname and cid in s:
                    s = s.replace(cid, cname)
            return s

        for i, rs in enumerate(raw_scenes):
            sid = str(rs.get("id") or f"sc{i + 1}")
            focalizer = str(rs.get("focalizer") or characters[0])
            others = [c for c in characters if c != focalizer]
            entities = [focalizer, *others]

            deltas: list[StateDelta] = []
            # 一场戏里变三件事是常态（三个人各自跨过一道坎）。
            # 原来只认单个对象，于是作者只能挑一个申报，其余的变成「正文里改了、
            # 卡片上没写」—— 那正是 `declaration_consistency` 要抓的虚报/漏报。
            # 与其让作者少写，不如让结构层写全。
            sd = rs.get("state_delta")
            if sd is None:
                sd = rs.get("state_deltas")
            items = sd if isinstance(sd, list) else ([sd] if isinstance(sd, dict) else [])
            for one in items:
                if not (isinstance(one, dict) and one.get("entity_id")):
                    continue
                try:
                    deltas.append(
                        StateDelta(
                            entity_id=str(one["entity_id"]),
                            attribute=str(one.get("attribute", "state")),
                            before=one.get("before", False),
                            after=one.get("after", True),
                        )
                    )
                except Exception:
                    continue

            vcs = str(rs.get("value_charge_start", "+"))
            vce = str(rs.get("value_charge_end", "-"))
            if vcs == vce:  # 强制 McKee 约束：保证价值翻转
                vce = "-" if vcs == "+" else "+"

            try:
                outcome = SceneOutcome(str(rs.get("outcome", "yes_but")))
            except ValueError:
                outcome = SceneOutcome.YES_BUT

            scene = SceneNode(
                id=sid,
                title=humanize(rs.get("title") or f"场景 {i + 1}"),
                focalizer=focalizer,
                narrator=focalizer,
                focalization=Focalization.INTERNAL,
                fabula_time=TimePoint(
                    day=int(rs.get("fabula_day", i)),
                    # 时间标记由结构层显式给出。没有就不写 ——
                    # 剧本渲染器据此在场景标题里省略时间，而不是猜一个钟点。
                    label=(str(rs["time_label"]).strip() or None)
                    if rs.get("time_label")
                    else None,
                ),
                sjuzhet_index=i,
                frequency=Frequency.SINGULATIVE,
                value=str(rs.get("value", "代价")),
                value_charge_start=vcs if vcs in "+-" else "+",  # type: ignore[arg-type]
                value_charge_end=vce if vce in "+-" else "-",  # type: ignore[arg-type]
                goal=humanize(rs.get("goal")),
                conflict=humanize(rs.get("conflict")),
                turning_point=humanize(rs.get("turning_point")),
                outcome=outcome,
                entities=entities,
                location=rs.get("location"),
                emotion=float(rs.get("emotion", 0.0)),
                state_deltas=deltas,
                is_branch_point=bool(rs.get("is_branch_point", False)),
                is_paywall_gate=bool(rs.get("is_paywall_gate", False)),
            )
            scenes.append(scene)

            ev = EventNode(
                id=f"ev_{sid}",
                summary=scene.turning_point,
                scene_id=sid,
                participants=entities,
                location=scene.location,
                preconditions=(
                    [Precondition(kind="prior_event", target=f"ev_{scenes[-2].id}")]
                    if len(scenes) > 1
                    else []
                ),
                effects=[Effect(kind="reveal", target=entities[0])],
                surprise=round(abs(scene.emotion), 2),
            )
            plot.add_event(ev)
            if len(scenes) > 1:
                plot.links.append(
                    CausalLink(src=f"ev_{scenes[-2].id}", dst=ev.id, kind="enables")
                )

        # 把作者承诺挂到具体场景上（承诺层的 must_hold_at 由此填充）
        self._bind_commitments(commitment, scenes)
        return plot, scenes

    @staticmethod
    def _bind_commitments(commitment: CommitmentLayer, scenes: list[SceneNode]) -> None:
        if not scenes:
            return
        n = len(scenes)
        for c in commitment.commitments:
            if c.kind == "theme":
                c.must_hold_at = [scenes[n // 2].id]
            elif c.kind == "ending":
                c.must_hold_at = [scenes[-1].id]
            elif c.kind == "moral_argument":
                c.must_hold_at = [scenes[-1].id]
            else:
                idx = min(n - 1, int((int(c.id.rsplit("_", 1)[-1]) / 5) * n))
                c.must_hold_at = [scenes[idx].id]
            # 注意：c.satisfied 保持 False（默认值），由后续场景内容决定
            # 是否兑现。_bind_commitments 只负责「排期」，不负责「判定兑现」。


# ---------------------------------------------------------------------------
# Stage 3：角色层 + 世界层
# ---------------------------------------------------------------------------


@dataclass
class CharacterEngine:
    gen: Generator

    def run(
        self, commitment: CommitmentLayer, scenes: list[SceneNode]
    ) -> tuple[CharacterLayer, StoryBible]:
        out = self.gen.generate(
            "characters",
            {
                "premise": commitment.premise,
                "controlling_idea": commitment.controlling_idea,
                "moral_argument": next(
                    (c.statement for c in commitment.commitments
                     if c.kind == "moral_argument"),
                    "",
                ),
                "scenes": [s.title for s in scenes],
            },
        )

        layer = CharacterLayer()
        for rc in out.get("characters", []) or []:
            cid = str(rc.get("id") or rc.get("name"))
            layer.add(
                Character(
                    id=cid,
                    name=str(rc.get("name", cid)),
                    aliases=list(rc.get("aliases", []) or []),
                    want=str(rc.get("want", "")),
                    need=str(rc.get("need", "")),
                    flaw=str(rc.get("flaw", "")),
                    arc_from=str(rc.get("arc_from", "")),
                    arc_to=str(rc.get("arc_to", "")),
                    # ⑦ 四卡锚：wound / lie 是「锚」，比 flaw 更可验证 ——
                    # 「傲慢」无法与任何东西比对，「只要我不在乎就不会再受伤」可以。
                    # 它们必须由生成阶段产出，不能等 TensionSeeder 现编：
                    # 张力是**从锚派生**的，锚本身不能是派生品。
                    wound=str(rc.get("wound", "")),
                    lie=str(rc.get("lie", "")),
                    voice=rc.get("voice"),
                    goals=[
                        GoalNode(
                            id=str(g.get("id") or f"g{i}"),
                            description=str(g.get("description", "")),
                            is_conscious=bool(g.get("is_conscious", True)),
                        )
                        for i, g in enumerate(rc.get("goals", []) or [])
                    ],
                    states=[CharacterState(at_day=0)],
                )
            )

        for ra in out.get("actants", []) or []:
            try:
                layer.actants.append(
                    ActantBinding(
                        role=ActantRole(str(ra.get("role"))),
                        entity_id=str(ra.get("entity_id")),
                        note=ra.get("note"),
                    )
                )
            except ValueError:
                continue

        bible = StoryBible()
        for re_ in out.get("entities", []) or []:
            eid = str(re_.get("id") or re_.get("name"))
            try:
                kind = EntityKind(str(re_.get("kind", "concept")))
            except ValueError:
                kind = EntityKind.CONCEPT
            bible.entities[eid] = Entity(
                id=eid,
                name=str(re_.get("name", eid)),
                kind=kind,
                description=str(re_.get("description", "")),
            )

        # 世界规则由前提反推（保证世界层与主题一致）
        bible.rules = [
            WorldRule(id="rule_1", statement=f"违反「{commitment.premise}」必付代价",
                      is_hard=True),
            WorldRule(id="rule_2", statement="信息一旦交付即不可撤回", is_hard=True),
        ]
        return layer, bible


# ---------------------------------------------------------------------------
# Stage 4：记忆层（自动播种）
# ---------------------------------------------------------------------------


@dataclass
class LoreSeeder:
    """从世界层与角色层自动生成 lore 条目。

    工业实践的关键点全部落实：
      - 角色条目常驻（is_constant），保证人设稳定
      - 世界设定用关键词触发 + 预算封顶
      - 秘密类条目加递归激活，形成链式召回
    """

    def run(self, ir: NarrativeIR) -> Lorebook:
        lore = Lorebook()

        # 世界与地点：常驻
        for e in ir.bible.entities.values():
            if e.kind in (EntityKind.LOCATION, EntityKind.ORGANIZATION):
                lore.add(
                    LoreEntry(
                        id=f"lore_{e.id}",
                        keys=[e.name, *(e.aliases or [])],
                        content=f"{e.name}：{e.description}",
                        is_constant=True,
                        order=150,
                        token_budget=120,
                        entity_id=e.id,
                    )
                )
            elif e.kind == EntityKind.ITEM:
                lore.add(
                    LoreEntry(
                        id=f"lore_{e.id}",
                        keys=[e.name, *(e.aliases or [])],
                        content=f"{e.name}：{e.description}",
                        order=140,
                        entity_id=e.id,
                    )
                )

        # 角色：常驻，含语言风格（保证声音一致）
        for c in ir.characters.characters.values():
            lore.add(
                LoreEntry(
                    id=f"lore_char_{c.id}",
                    keys=[c.name, *(c.aliases or [])],
                    content=(
                        f"{c.name}。欲望：{c.want}。需求：{c.need}。缺陷：{c.flaw}。"
                        f"弧光：{c.arc_from} → {c.arc_to}。"
                        + (f"语言风格：{c.voice}。" if c.voice else "")
                    ),
                    is_constant=True,
                    order=190,
                    token_budget=200,
                    entity_id=c.id,
                )
            )

        # 世界规则：关键词触发
        for r in ir.bible.rules:
            lore.add(
                LoreEntry(
                    id=f"lore_{r.id}",
                    keys=["规则", "设定", "代价"],
                    content=r.statement,
                    logic=KeyLogic.AND_ANY,
                    order=120,
                    recursion=RecursionPolicy(allow_outgoing=True, max_steps=2),
                )
            )
        return lore


# ---------------------------------------------------------------------------
# Stage 4.5：台账层（悬念 + 知情矩阵）
# ---------------------------------------------------------------------------


@dataclass
class LedgerSeeder:
    """两本台账的自动播种。

    长篇最容易写崩的地方，恰恰是最该机器维护的地方：
      - 谜题台账：埋了什么、计划何时解、有没有烂尾
      - 知情矩阵：谁在第几天知道了什么

    这两本账人工维护必错（几百章规模下人脑记不住），
    而一旦错了，读者立刻能感觉到「吃书」。所以它是自动派生的，
    不是让作者手填的表单。
    """

    resolve_lag: int = 2
    leave_open_tail: int = 0
    """结尾故意留白的谜题数。留白是手法，烂尾是事故 —— 所以默认 0，
    需要钩子式结尾时显式调大。"""

    def run(
        self, ir: NarrativeIR
    ) -> tuple[list[Enigma], list[KnowledgeFact]]:
        scenes = ir.ordered_scenes()
        if not scenes:
            return [], []

        enigmas: list[Enigma] = []

        # 可埋设的场景范围：默认不含最后一场。
        # 理由：终局是**回收**的位置，不是埋设的位置。在最后一场新埋一个
        # 注定无处可收的谜题，只会让台账凭空多出一条烂尾项。
        # 真要在结尾留钩子（连载常用手法），显式设 leave_open_tail >= 1。
        last = len(scenes)
        plantable_end = last - 1 if self.leave_open_tail == 0 else last
        closed_end = max(0, plantable_end - self.leave_open_tail)

        # 已回收的部分
        for i in range(closed_end):
            s = scenes[i]
            target_idx = min(last - 1, i + self.resolve_lag)
            target = scenes[target_idx]
            # 知情者必须同时包含「埋设场的聚焦者」与「回收场的聚焦者」，
            # 否则回收场的聚焦者会在内聚焦下凭空知道一个他不知道的事 ——
            # 这正是 focalizer_boundary 校验器要抓的越界。
            knowers = [s.focalizer]
            if target.focalizer not in knowers:
                knowers.append(target.focalizer)
            enigmas.append(
                Enigma(
                    id=f"en_{s.id}",
                    question=f"{s.value}最后会落到谁手里？",
                    planted_at_scene=s.id,
                    state=EnigmaState.RESOLVED,
                    revealed_to=knowers,
                    planned_resolution_scene=target.id,
                    resolved_at_scene=target.id,
                    # 草蛇灰线 = 早埋晚收；突转 = 紧邻回收
                    device="草蛇灰线" if target_idx - i >= 2 else "突转",
                )
            )

        # 故意留白的部分（续作钩子）。
        # 注意：这里**不填** planned_resolution_scene —— 留白是手法，
        # 但「埋了没登记回收点」必须被校验器喊出来，这是台账存在的意义。
        for i in range(closed_end, plantable_end):
            s = scenes[i]
            enigmas.append(
                Enigma(
                    id=f"en_{s.id}",
                    question=f"{s.value}最后会落到谁手里？",
                    planted_at_scene=s.id,
                    state=EnigmaState.POSED,
                    revealed_to=[s.focalizer],
                    device="悬念留白",
                )
            )

        facts: list[KnowledgeFact] = []
        for s in scenes:
            for d in s.state_deltas:
                facts.append(
                    KnowledgeFact(
                        id=f"fact_{s.id}_{d.entity_id}_{d.attribute}",
                        content=f"{d.entity_id} 的 {d.attribute}：{d.before} → {d.after}",
                        known_by={d.entity_id: s.fabula_time.day},
                    )
                )
        return enigmas, facts


# ---------------------------------------------------------------------------
# Stage 4.6：张力播种（Loom 第一个**向前看**的引擎）
# ---------------------------------------------------------------------------


@dataclass
class TensionSeeder:
    """把「角色信以为真的东西」变成「接下来可以写什么」。

    Loom 其余引擎要么在生成（Premise / Cast / Structure / Character），
    要么在播种既有事实（Lore / Ledger），要么在体检（Critic）。
    本引擎是第一个**向前看**的：它不修改任何已有字段的语义，只往
    `ir.tension_points` 放生成资产 —— 每条都带 `suggestion`，供作者
    （或下一轮 StructureEngine）当约束用。

    数据从哪来：**从故事已经声明的结构反推，不编造内容。**
    ────────────────────────────────────────────────────────────
      * `objective_truth[lie] = False`
        —— `lie` 的定义就是「角色信以为真、但故事世界不成立」的命题。
        这是 `Character.lie` 的语义本身，不是额外假设。
      * 角色相信自己的 lie（`value=True`，来源「误解」）
        —— 同理。来源为「误解」时 `Belief` 会自动置 `is_erroneous`，
        而真值层说它是 `False`，两者**一致**，所以 `belief_consistency`
        不会误报。这不是巧合：一个诚实的播种器不该制造它自己要抓的缺陷。
      * `active_goals` 取角色的**显性目标**与 `want`
        —— 两个人追同一个目标就是目标冲突，这是角色层已有的信息，
        不是新编的。

      * **不播种 `known_secrets`。** 秘密需要一份作者声明的「谁知道什么」
        台账。从 `wound` 反推等于替作者发明一个他没声明过的秘密，
        而 `secret_reveal_ordering` 会因此报出一个作者无法理解的 WARN ——
        **播种器制造自己的反例，是本项目最该避免的那种自欺。**
        已登记的悬念由 `LedgerSeeder` 负责（那是显式台账，性质不同）。
      * **不播种递归信念**（A 以为 B 以为 C…）。那是最深一层的创作内容，
        不是结构反推。因此 `RECURSIVE_MISMATCH` 不在默认产出里。
        这是**有意的能力边界**，不是缺陷。

    幂等：重复 `run()` 只补齐缺失项、不重复追加 ——
    否则每跑一轮，信念冲突就会翻一倍。
    """

    max_points: int = 12
    """产出上限。张力点是给作者看的清单，不是给机器算的分 ——
    一份 40 条的清单没人会读，而没人读的报表等于不存在。"""

    #: 播种 lie 信念时给的置信度先验。不随章节数衰减
    #: （源项目 `advance_chapter()` 的 ×0.95「角色会遗忘」是语义错误，
    #: 见 `loom/ir/tom.py` 的立场说明）。
    lie_confidence: float = 0.8

    def run(self, ir: NarrativeIR) -> list[TensionPoint]:
        self._seed_truth(ir)
        self._seed_beliefs(ir)
        states = {
            cid: ch.belief_state
            for cid, ch in ir.characters.characters.items()
            if ch.belief_state is not None
        }
        if not states:
            return []
        return derive_tension_points(states, ir.objective_truth)[: self.max_points]

    # -- 播种 --

    @staticmethod
    def _seed_truth(ir: NarrativeIR) -> None:
        """lie → 真值层。已存在的条目不动（作者显式给的真值优先）。"""
        for ch in ir.characters.characters.values():
            lie = (ch.lie or "").strip()
            if lie and lie not in ir.objective_truth:
                ir.objective_truth[lie] = False

    def _seed_beliefs(self, ir: NarrativeIR) -> None:
        for ch in ir.characters.characters.values():
            bs = ch.belief_state or CharacterBeliefState()

            lie = (ch.lie or "").strip()
            if lie and lie not in bs.world_beliefs:
                bs.world_beliefs[lie] = Belief(
                    proposition=lie,
                    value=True,
                    confidence=self.lie_confidence,
                    source=BeliefSource.MISUNDERSTANDING,
                )

            if not bs.active_goals:
                goals = [
                    g.description
                    for g in ch.goals
                    if g.is_conscious and g.description
                ]
                if ch.want:
                    goals.append(ch.want)
                bs.active_goals = goals

            ch.belief_state = bs


# ---------------------------------------------------------------------------
# Stage 5：正文
# ---------------------------------------------------------------------------


@dataclass
class ScriptedScene:
    """`Scripter` 的产物：正文 + 自申报。

    为什么不直接返回 `str`：① CHANGES 协议要求正文与声明**分开**回流，
    否则调用方要自己再解析一次，等于把解析责任推给了每个调用点。
    `prose` 已剥掉声明 —— 声明绝不能漏进正文（那会出现在小说里）。
    """

    prose: str
    declared: dict[str, Any] = field(default_factory=dict)
    raw: str | None = None
    note: str | None = None


@dataclass
class Scripter:
    gen: Generator

    def run(
        self,
        ir: NarrativeIR,
        scene: SceneNode,
        *,
        target_words: int = 800,
        prev_tail: str = "",
    ) -> ScriptedScene:
        # 记忆层：只注入本章相关条目，绝不注入全文
        probe = " ".join(
            [scene.title, scene.goal, scene.conflict, scene.turning_point,
             *scene.entities]
        )
        active = ir.lore.compile(probe, budget_tokens=1200)
        lore_text = "\n".join(f"- {e.content}" for e in active) or "（无）"

        # id -> 显示名。IR 内部用 id（机器友好），提示词与正文必须用名字。
        # 这个边界如果不在这一层守住，正文里就会冒出内部标识 ——
        # 这是最典型的「架构泄漏到产品」事故。
        display: dict[str, str] = {}
        for c in ir.characters.characters.values():
            display[c.id] = c.name
        for e in ir.bible.entities.values():
            display[e.id] = e.name

        def name_of(x: str) -> str:
            return display.get(x, x)

        char_state = []
        for cid in scene.entities:
            ch = ir.characters.characters.get(cid)
            if not ch:
                continue
            st = ch.state_at(scene.fabula_time.day)
            char_state.append(
                f"- {ch.name}：{st.condition if st else '正常'}；"
                f"欲望 {ch.want}；语言风格 {ch.voice or '未定义'}"
            )

        cast_names = [name_of(cid) for cid in scene.entities]

        out = self.gen.generate(
            "prose",
            {
                # 媒介形态规格。不传的话模型只会写小说散文 ——
                # 这是「选了剧本却产出小说」的根因，不是排版能补救的。
                "medium": ir.medium.value,
                "medium_craft": craft_brief(ir.medium),
                "length_hint": length_hint(ir.medium, target_words),
                "title": scene.title,
                "focalizer": name_of(scene.focalizer),
                "focalizer_id": scene.focalizer,
                "focalization": scene.focalization.value,
                "goal": scene.goal,
                "conflict": scene.conflict,
                "turning_point": scene.turning_point,
                "value": scene.value,
                "value_charge_start": scene.value_charge_start,
                "value_charge_end": scene.value_charge_end,
                "outcome": scene.outcome.value,
                "emotion": scene.emotion,
                "entities": ", ".join(cast_names),
                "cast": cast_names,
                "lore": lore_text,
                "character_state": "\n".join(char_state) or "（无）",
                "prev_tail": prev_tail[-200:] if prev_tail else "（这是开场）",
                "target_words": target_words,
                # ① CHANGES：把场景卡声称的变化给模型看，让它对照着申报
                "state_deltas": "\n".join(
                    f"- {name_of(d.entity_id)}.{d.attribute}：{d.before} → {d.after}"
                    for d in scene.state_deltas
                )
                or "（场景卡没有声明变化）",
                # 机器视图保留原始 id，方便需要结构化输入的模型
                "scene": scene.model_dump(mode="json"),
            },
        )
        # ① 正文与声明分流。解析永不抛 —— 拿不到声明是降级，不是失败。
        decl = split(str(out.get("prose", "")))
        return ScriptedScene(
            prose=decl.prose.strip(),
            declared=decl.changes,
            raw=decl.raw,
            note=decl.note,
        )


# ---------------------------------------------------------------------------
# Stage 6.5：提案 —— 结构类问题的**唯一**出口
# ---------------------------------------------------------------------------

#: finding code -> 被改的**字段名**。用于 `Diff.field`。
#:
#: 为什么要这张表而不是直接拿 code 当 field：遥测的 `by_field()` 要回答的是
#: 「哪类**字段**的提案最可信」，而不是「哪个校验器最常报警」。后者是校验器
#: 的属性，前者才是产品的属性 —— 只有前者能指导「下一版该把哪类建议做得更准」。
#: 未登记的 code 回退成 code 本身（宁可粒度粗，也不要猜错字段）。
_FIELD_OF: dict[str, str] = {
    "value_charge_flip": "value_charge_end",
    "state_delta": "state_deltas",
    "state_transition_integrity": "state_deltas",
    "commitment_satisfied": "commitments",
    "enigma_resolution": "enigmas",
    "emotion_curve_match": "emotion",
    "li_yu_main_brain": "commitments",
    "li_yu_reduce_threads": "value",
    "mao_repeat_variation": "turning_point",
    "actant_collision": "actants",
    "focalizer_boundary": "focalization",
    "causal_chain_integrity": "preconditions",
    "hook_cadence": "value_charge_end",
    "paywall_gate_present": "is_paywall_gate",
    "template_coverage": "beat_template",
    "thread_budget": "value",
    "outcome_distribution": "outcome",
    "knowledge_matrix": "revealed_to",
    "revelation_regression": "planted_at_scene",
    "timeline_monotonic": "fabula_time",
    "entity_reference": "entities",
    "alias_collision": "aliases",
    "world_rule_violation": "is_hard",
    "provenance_coverage": "origin",
    "numeric_fact_consistency": "prose",
    "pattern_saturation": "value",
    "declaration_consistency": "declared",
    "lie_arc_closure": "lie",
    "belief_consistency": "belief_state",
    "secret_reveal_ordering": "known_secrets",
    "relation_temporal": "valid_from_day",
    # -- Truby 四元（欲望 / 需求）与 Fan 分层（正文 vs 结构声明）--
    # 两个 Truby 校验器都指向 `need`，但含义不同：
    #   desire_need_conflict        需求与欲望是否两个东西 → 改 need 的定义
    #   need_revelation_at_climax   需求有没有在高潮兑现 → 改高潮场次
    # 映射只能带一个字段名，粒度到此为止；区分靠 proposal 的 rationale。
    "desire_need_conflict": "need",
    "need_revelation_at_climax": "need",
    "prose_structure_fidelity": "prose",
    # P6 互动叙事分支一致性：映射到 state_deltas（分支建立在状态增量上）。
    "branch_consistency": "state_deltas",
}


def _proposal_ids(findings: list) -> list[str]:
    """给一批 finding 派生**确定性**的提案 id。

    确定性是幂等的前提，而幂等不是洁癖：`critique()` 会被调用多次
    （多轮修订、外部重跑），如果 id 依赖「当前已登记了哪些提案」，
    第二次调用就会给同一条发现分配一个新 id，于是提案清单每跑一轮翻一倍。

    所以消歧后缀取自**该发现在本批里的序号**，与 `ir.proposals` 的现状无关：
    同一份体检永远得到同一批 id。

    消歧是必需的：同一个校验器可以对同一张卡报多条
    （`enigma_resolution` 对三个未回收的谜题各报一条，且都没有 scene_id）。
    """
    counts: dict[str, int] = {}
    out: list[str] = []
    for f in findings:
        base = f"prop_{f.code}_{f.scene_id or f.entity_id or 'global'}"
        n = counts.get(base, 0) + 1
        counts[base] = n
        out.append(base if n == 1 else f"{base}_{n}")
    return out


def _snapshot(ir: NarrativeIR, finding) -> Any:
    """目标卡当前的结构快照 —— 作者靠它看清「改之前是什么样」。

    刻意是**快照**而不是「字段原值」：结构问题的「代价」往往不在这一个字段上
    （改 `outcome` 会牵动 `value_charge` 与 `turning_point`），
    只给一个字段会让作者以为改动是局部的。
    """
    s = ir.scene(finding.scene_id) if finding.scene_id else None
    if s is None:
        return {
            "scenes": len(ir.scenes),
            "characters": len(ir.characters.characters),
            "medium": ir.medium.value,
        }
    return {
        "title": s.title,
        "value": s.value,
        "value_charge": f"{s.value_charge_start}→{s.value_charge_end}",
        "outcome": s.outcome.value,
        "turning_point": s.turning_point,
        "emotion": s.emotion,
    }


@dataclass
class Proposer:
    """把结构类问题转成「可一键采纳」的 Diff 提案 —— **绝不自动应用**。

    出处：Horvitz (1999) 混合主动界面「系统可以提议，控制权必须留在用户手里」；
    Amershi et al. (2019) guideline 6「拒绝必须是廉价的一次性操作」。
    详见 `loom/ir/proposal.py` 的模块 docstring。

    与 `CriticLoop` 的分工（作者既定边界，不擅自扩大）：
        文风类（slop）  → CriticLoop **自动**修（保持现状）
        结构类          → 本类产出 Diff 提案，作者 accept / reject

    为什么结构类不能自动修：结构改动会毁掉作者意图。
    但「留给人决策」如果没有载体，等于没发生 —— 原先的 `CriticLoop` 只是把
    结构问题打进日志，作者读完就没有然后了。本类给它一个可裁决的载体。

    **本类不生成可自动应用的补丁。** `before` 是目标卡当前的结构快照
    （供作者看清代价），`after` 是建议文本。两者都是**给人读的**：
    采纳意味着作者认可这个方向，具体怎么改由作者或下一轮生成决定。
    做成「机器可应用的 patch」会立刻越过那条边界 —— 那时「永不静默改写」
    就只剩下一句口号了。

    幂等：提案 id 由 (code, 场景, 实体) **在本批体检里的序号**派生，
    与「已经登记了哪些提案」无关，因此重复 `run()` 不会累积副本。
    没有这一条，每跑一轮体检就会多出一份同样的提案清单。

    「哪些问题算结构类」用的是一条**可机检的判据**，不是前缀黑名单：
    **只有 registry 里注册过的校验器才产出结构类发现。**
    文风/工艺检测器（anti_slop / craft / dress / transportation / cognitive）
    都不在 registry 里，它们的 code 是 `slop:*` / `craft:*` / `audit:*` /
    `cognitive_load_window`，天然被排除。

    为什么不用前缀表：这条路径上真的踩过坑。原先写的是
    `("slop:", "craft:", "dress:", "transport:", "cognitive:")`，
    而实际上 `dress.py` 与 `transportation.py` 产出的是 `audit:*`，
    cognitive 产出的是不带前缀的 `cognitive_load_window` ——
    **两个错的前缀让「风格漂移」和「传输度过低」被当成结构缺陷排队等作者裁决。**
    前缀表是手写的，registry 是派生的；手写的清单必然漂移。
    """

    max_proposals: int = 20
    """一次体检最多登记多少条提案。超出的部分不登记 —— 一份 200 条的
    待办清单不会被处理，而没被处理的提案等于没有提案。"""

    def run(self, ir: NarrativeIR, report) -> list[Diff]:
        # 判据：只有注册过的校验器才产出结构类发现（见类 docstring）。
        # 从 registry 现取，不手写清单。
        registered = set(available())
        findings = [
            f for f in [*report.errors, *report.warnings] if f.code in registered
        ]
        ids = _proposal_ids(findings)

        seen = {d.id for d in ir.proposals}
        out: list[Diff] = []
        for f, did in zip(findings, ids):
            if did in seen:
                continue
            if len(out) >= self.max_proposals:
                break
            seen.add(did)
            out.append(
                Diff(
                    id=did,
                    target_card=f"scene:{f.scene_id}" if f.scene_id else "ir",
                    field=_FIELD_OF.get(f.code, f.code),
                    before=_snapshot(ir, f),
                    after=f.suggestion or f.message,
                    rationale=f.message,
                    source_card=f"validator:{f.code}",
                    # status 保持默认的 pending —— **绝不默认生效**。
                )
            )
        ir.proposals.extend(out)
        return out


# ---------------------------------------------------------------------------
# Stage 6：体检 -> 修订循环
# ---------------------------------------------------------------------------


@dataclass
class CriticLoop:
    """生成与修订分离。

    重要：Critic 可以用与 Scripter 不同的 Generator（不同模型或不同系统提示），
    以避免同模型自评的自我确认偏差。这是本类的核心设计意图。

    两类问题走两条完全不同的路（**这是作者的既定边界，不擅自扩大**）：
        文风类（slop）  → **自动**改。改错了也不伤结构，且人改不如机器快。
        结构类          → 交给 `Proposer` 生成 Diff 提案，**不自动应用**。
                          自动改结构会毁掉作者意图。

    原先结构类只是被打进日志，作者读完就没有然后了 ——
    「留给人决策」如果没有载体，等于没发生。`Proposer` 补上了这个载体。
    """

    reviser: Generator
    max_rounds: int = 2
    slop_threshold: int = 65
    propose: bool = True
    """是否把结构类问题转成 Diff 提案。关掉它只影响「有没有提案」，
    不影响体检结论 —— 提案是附加产物，不是体检的一部分。"""

    budget: RepairBudget | None = None
    """修复预算（P3）。None 时按 max_rounds 派生一份。

    为什么必须有：ConWriter（EMNLP 2026）在 GPT-5 / 6K–12K 上因
    「修复遵从 vs 长度控制」互锁而**不收敛** —— 验证器与生成器会互相
    牵着对方跑，不设预算就会在「修不完的修复循环」里烧完 token。
    触顶必须**停止并报告**，不能静默继续。
    """

    def run(self, ir: NarrativeIR) -> tuple[NarrativeIR, list[str]]:
        log: list[str] = []
        budget = self.budget or RepairBudget(
            max_rounds=self.max_rounds, started_at=time.time()
        )
        for rnd in range(1, self.max_rounds + 1):
            # 预算闸：每一轮开始前查。触顶即停，并把代价写进日志。
            if budget.exhausted(now=time.time()):
                log.append(
                    f"第 {rnd} 轮未开始：修复预算已触顶"
                    f"（{budget.render(now=time.time())}）——"
                    "停止并报告，不静默继续"
                )
                break
            budget.rounds = rnd
            report = run_all(ir)
            issues = report.errors + report.warnings

            # 只修订「可自动修」的问题：文风类。结构类问题需要人决策，不自动改。
            #
            # ⚠ 这里**必须**用 `scan_ir`，不能从 `report.findings` 里筛 `slop:` 前缀。
            # slop 结论**不在** `run_all` 的报告里 —— 它走的是 advisory 通道
            # （见 `cmd_audit` 的 `add_advisory(*scan_slop_ir(ir))`），
            # 而 registry 里根本没有注册任何 `slop:*` 校验器。
            # 原实现写的是 `[f for f in issues if f.code.startswith("slop:")]`，
            # `issues` 来自 `run_all`，于是 `slop_targets` **恒为空**。
            #
            # ⚠ 第二处：原实现在「没有结构问题」时**先 break**，
            # 于是即使文风有得改也轮不到它 —— 结构干净恰恰是**最常见的**情况。
            # 这两处合起来，「文风类自动改」这条既定边界从未真正生效过。
            # （是跑 `max_rounds` 实验时暴露的：1/2/3/4/5 轮结果完全一致，
            #   因为循环体里根本没有任何事发生。）
            by_scene: dict[str, list] = {}
            for f in scan_ir(ir):
                if f.scene_id:
                    by_scene.setdefault(f.scene_id, []).append(f)
            # 只有分数低于阈值的场景才值得改；`scan_ir` 会把 INFO 也报出来，
            # 但「有一处疑似」不等于「这一场需要重写」。
            pending_scenes = {
                sid: fs
                for sid, fs in by_scene.items()
                if (ir.scene(sid) and ir.scene(sid).prose
                    and scan_slop(ir.scene(sid).prose, scene_id=sid).score
                    < self.slop_threshold)
            }

            if not issues and not pending_scenes:
                log.append(f"第 {rnd} 轮：无结构问题，也无待修的文风问题")
                break
            log.append(
                f"第 {rnd} 轮：{len(report.errors)} 错误 / {len(report.warnings)} 警告"
                f"（健康分 {report.score()}）"
                + (f"，{len(pending_scenes)} 场待去 AI 味" if pending_scenes else "")
            )

            for sid, fs in pending_scenes.items():
                scene = ir.scene(sid)
                rep = scan_slop(scene.prose, scene_id=sid)
                findings_text = "\n".join(f.message for f in fs)
                out = self.reviser.generate(
                    "revise",
                    {"prose": scene.prose, "findings": findings_text},
                )
                new_prose = str(out.get("prose", "")).strip()
                if new_prose and new_prose != scene.prose:
                    # 记账：同一个 (卡, 字段) 只计一次；超 max_field_edits 即停。
                    if not budget.note_edit(sid, "prose"):
                        log.append(
                            f"    {sid} 未修订：字段编辑预算已触顶"
                            f"（{budget.render(now=time.time())}）"
                        )
                        continue
                    scene.prose = new_prose
                    log.append(f"    {sid} 已修订（去 AI 味 {rep.score} → "
                               f"{scan_slop(new_prose, sid).score}）")

        final = run_all(ir)
        # 结构类问题 → 提案（**不自动应用**）。放在最后：提案要基于最终状态，
        # 而不是某一轮中途的状态，否则作者看到的 before 已经过期了。
        if self.propose:
            proposals = Proposer().run(ir, final)
            # 冲突消解（P3）：同一 (卡, 字段) 被两条互斥建议同时改 →
            # 记为 conflicted 交人裁决，而不是让机器二选一。
            # 复用已有的 DiffStatus.CONFLICTED 语义，不新造概念。
            conflicts = detect_conflicts(proposals)
            if conflicts:
                mark_conflicted(proposals, conflicts=conflicts)
                log.append(
                    f"⚠ {len(conflicts)} 组互斥建议已标记为 conflicted"
                    "（交作者裁决，机器不替人二选一）："
                )
                log.extend("    " + c.render() for c in conflicts[:5])
            if proposals:
                log.append(
                    f"结构提案 {len(proposals)} 条（待作者裁决，**不自动应用**）"
                )
            # 觉察回显：让「作者做了多少判断」在**写作时**可见，而不是申诉时才导出。
            # 依据 CHI 2026 Reactive Writing —— 作者察觉不到 AI 对自己方向的影响，
            # 却感觉完全掌控。详见 loom/provenance/awareness.py。
            # 放在提案之后：提案刚生成时正是「读建议 → 挑一个」最容易发生的时刻。
            log.extend("  " + ln for ln in awareness_block(ir))
        log.append(f"最终健康分 {final.score()}/100")
        return ir, log
