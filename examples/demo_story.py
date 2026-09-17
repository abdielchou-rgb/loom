"""示例：一个完整的 Narrative IR 实例。

刻意构造得「有问题」，以便体检报告有东西可报：
    - 一个零增量场景
    - 一个未回收的谜题（烂尾信号）
    - 一条未兑现的作者承诺
    - 一处别名冲突
    - 一段带 AI 味的正文
这比一个完美样例更能证明校验器真的在工作。
"""

from __future__ import annotations

from loom.ir.enums import (
    ActantRole,
    ArcShape,
    ChunkOrigin,
    EntityKind,
    EnigmaState,
    Focalization,
    Frequency,
    KeyLogic,
    Medium,
    SceneOutcome,
)
from loom.ir.models import (
    ActantBinding,
    CausalLink,
    Character,
    CharacterLayer,
    CharacterState,
    Choice,
    Commitment,
    CommitmentLayer,
    Condition,
    Effect,
    Entity,
    Enigma,
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


def build_demo_ir() -> NarrativeIR:
    bible = StoryBible(
        chronotope="threshold",
        entities={
            "loc_inn": Entity(
                id="loc_inn", name="听雪楼", kind=EntityKind.LOCATION,
                aliases=["客栈"], description="边陲小镇的客栈，故事主要发生地",
            ),
            "loc_cliff": Entity(
                id="loc_cliff", name="断云崖", kind=EntityKind.LOCATION,
                description="镇外悬崖，终局地点",
            ),
            "item_letter": Entity(
                id="item_letter", name="密信", kind=EntityKind.ITEM,
                aliases=["信", "那封信"], description="父亲留下的密信",
            ),
            "org_court": Entity(
                id="org_court", name="锦衣卫", kind=EntityKind.ORGANIZATION,
                description="追捕主角的朝廷机构",
            ),
        },
        relations=[
            Relation(src="ch_lin", dst="ch_shen", kind="师徒", polarity=0.6),
            Relation(src="ch_shen", dst="org_court", kind="效忠", polarity=0.8),
        ],
        rules=[
            WorldRule(id="rule_1", statement="武功内力不可凭空恢复，需静养", is_hard=True),
            WorldRule(id="rule_2", statement="密信一旦拆封即无法复原", is_hard=True),
            WorldRule(id="rule_3", statement="镇上没有官府常驻", is_hard=True),
        ],
    )

    plot = PlotLayer()
    plot.add_event(
        EventNode(
            id="ev_open", summary="林砚在听雪楼收到一封无名密信",
            scene_id="sc1", participants=["ch_lin"], location="loc_inn",
            effects=[Effect(kind="create", target="item_letter")],
        )
    )
    plot.add_event(
        EventNode(
            id="ev_pursue", summary="锦衣卫包围客栈，林砚突围",
            scene_id="sc2", participants=["ch_lin", "ch_shen"], location="loc_inn",
            preconditions=[
                Precondition(kind="location", target="ch_lin", value="loc_inn"),
                Precondition(kind="prior_event", target="ev_open"),
            ],
            effects=[Effect(kind="move", target="ch_lin", value="loc_cliff")],
            surprise=0.7,
        )
    )
    plot.add_event(
        EventNode(
            id="ev_truth", summary="沈砚揭露自己是锦衣卫，且是林砚的杀父仇人",
            scene_id="sc4", participants=["ch_lin", "ch_shen"], location="loc_cliff",
            preconditions=[
                Precondition(kind="prior_event", target="ev_pursue"),
                Precondition(kind="inventory", target="item_letter"),
            ],
            effects=[
                Effect(kind="reveal", target="item_letter", note="信中真相"),
                Effect(kind="set_attribute", target="ch_shen",
                       attribute="allegiance", value="opponent"),
            ],
            surprise=0.95,
        )
    )
    plot.links = [
        CausalLink(src="ev_open", dst="ev_pursue", kind="enables"),
        CausalLink(src="ev_pursue", dst="ev_truth", kind="requires"),
    ]

    characters = CharacterLayer()
    characters.add(
        Character(
            id="ch_lin", name="林砚", aliases=["砚儿"],
            want="查出父亲死因", need="学会信任他人", flaw="偏执，宁可独自承担",
            arc_from="孤僻独行者", arc_to="愿意托付同伴",
            voice="短句，少修饰，多用反问",
            goals=[
                GoalNode(id="g1", description="找到父亲之死的真相"),
                GoalNode(id="g2", description="活着离开听雪楼"),
                GoalNode(id="g3", description="不再信任任何人", is_conscious=False),
            ],
            states=[
                CharacterState(at_day=0, location="loc_inn", condition="警觉",
                               knows=["fact_letter"]),
                CharacterState(at_day=2, location="loc_cliff", condition="重伤",
                               knows=["fact_letter", "fact_betrayal"]),
            ],
        )
    )
    characters.add(
        Character(
            id="ch_shen", name="沈砚",
            want="完成任务并灭口", need="赎回当年的怯懦", flaw="用忠诚掩盖愧疚",
            arc_from="冷面护卫", arc_to="坦白的罪人",
            voice="敬语，句式完整，情绪藏在礼节后",
            goals=[GoalNode(id="g4", description="找到父亲之死的真相")],  # 与主角目标相撞
            states=[CharacterState(at_day=0, location="loc_inn")],
        )
    )
    characters.actants = [
        ActantBinding(role=ActantRole.SUBJECT, entity_id="ch_lin"),
        ActantBinding(role=ActantRole.OBJECT, entity_id="item_letter"),
        ActantBinding(role=ActantRole.SENDER, entity_id="ch_lin", note="亡父的遗愿"),
        ActantBinding(role=ActantRole.RECEIVER, entity_id="ch_lin"),
        ActantBinding(role=ActantRole.OPPONENT, entity_id="org_court"),
        ActantBinding(role=ActantRole.OPPONENT, entity_id="ch_shen", note="反转：护卫即追兵"),
        ActantBinding(role=ActantRole.HELPER, entity_id="ch_shen"),
    ]

    commitment = CommitmentLayer(
        premise="偏执地独自承担一切，会把最该信任的人推成敌人。",
        controlling_idea="真正的背叛不是被出卖，而是从未允许别人靠近。",
        logline="一个只信自己的少年，在逃亡途中发现追杀他的正是他唯一的同伴。",
        arc_shape=ArcShape.MAN_IN_A_HOLE,
        ending_anchor="林砚把密信交给沈砚，选择相信他一次 —— 然后独自走下断云崖。",
        commitments=[
            Commitment(
                id="cm_theme", kind="theme",
                statement="主角必须至少一次主动求助他人",
                must_hold_at=["sc3"], severity="error", satisfied=True,
            ),
            Commitment(
                id="cm_turn", kind="required_turn",
                statement="沈砚的身份反转必须在第三幕前揭示",
                must_hold_at=["sc4"], severity="error", satisfied=True,
            ),
            Commitment(
                id="cm_moral", kind="moral_argument",
                statement="主题论证收束：信任的代价 vs 不信任的代价必须被同时呈现",
                must_hold_at=["sc5"], severity="error", satisfied=False,  # 故意未兑现
            ),
        ],
    )

    scenes = [
        SceneNode(
            id="sc1", title="听雪楼·无名之信",
            focalizer="ch_lin", narrator="ch_lin", focalization=Focalization.INTERNAL,
            fabula_time=TimePoint(day=0, label="雪夜"), sjuzhet_index=0,
            frequency=Frequency.SINGULATIVE,
            value="信任", value_charge_start="+", value_charge_end="-",
            goal="林砚想弄清密信是谁放的",
            conflict="客栈里没人承认，而他不愿开口问第二遍",
            turning_point="他选择拆信而非追问 —— 独行的第一次代价",
            outcome=SceneOutcome.NO_AND, entities=["ch_lin", "item_letter"],
            location="loc_inn", emotion=-0.5,
            state_deltas=[
                StateDelta(entity_id="ch_lin", attribute="knows_letter",
                           before=False, after=True)
            ],
            prose=(
                "雪落进檐下，化在水里，看不出形状。\n"
                "信在桌上，没有署名。林砚盯着它看了很久，久到蜡烛短了一截。\n"
                "他没有问。这不仅是犹豫，而是他早已习惯把问题咽回去。\n"
                "拆开的时候，纸边割破了指腹，血珠很小，他没擦。"
            ),
            origin=ChunkOrigin.AI_EDITED,
        ),
        SceneNode(
            id="sc2", title="听雪楼·围",
            focalizer="ch_lin", narrator="ch_lin", focalization=Focalization.INTERNAL,
            fabula_time=TimePoint(day=1, label="破晓"), sjuzhet_index=1,
            frequency=Frequency.SINGULATIVE,
            value="信任", value_charge_start="-", value_charge_end="+",
            goal="林砚要活着冲出客栈",
            conflict="锦衣卫封了前后门，而沈砚挡在他身前",
            turning_point="沈砚替他挡刀 —— 他第一次接受别人的保护",
            outcome=SceneOutcome.YES_BUT, entities=["ch_lin", "ch_shen"],
            location="loc_inn", emotion=-0.7,
            state_deltas=[
                StateDelta(entity_id="ch_lin", attribute="location",
                           before="loc_inn", after="loc_cliff")
            ],
            prose="刀锋擦过木柱，木屑落在两人之间。沈砚没有回头，只说了两个字：走。",
            origin=ChunkOrigin.AI_GENERATED,
        ),
        SceneNode(
            id="sc3", title="断云崖·静夜",
            focalizer="ch_lin", narrator="ch_lin", focalization=Focalization.INTERNAL,
            fabula_time=TimePoint(day=1, label="夜"), sjuzhet_index=2,
            frequency=Frequency.ITERATIVE,
            value="信任", value_charge_start="+", value_charge_end="+",  # 零转折，故意
            goal="林砚想处理伤口",
            conflict="（无）",
            turning_point="（无实质转折 —— 本场为纯粹过场）",
            outcome=SceneOutcome.YES, entities=["ch_lin", "ch_shen"],
            location="loc_cliff", emotion=-0.3,
            state_deltas=[],  # 零增量，故意
            prose="他处理了伤口。空气仿佛凝固，时间仿佛静止，他感到无比疲惫。",
            origin=ChunkOrigin.AI_GENERATED,
        ),
        SceneNode(
            id="sc4", title="断云崖·刀",
            focalizer="ch_lin", narrator="ch_lin", focalization=Focalization.INTERNAL,
            fabula_time=TimePoint(day=2, label="黎明"), sjuzhet_index=3,
            frequency=Frequency.SINGULATIVE,
            value="信任", value_charge_start="+", value_charge_end="-",
            goal="林砚想确认沈砚的来历",
            conflict="沈砚的腰牌掉在地上，锦衣卫的纹样",
            turning_point="沈砚承认：他一直在找的是同一封信",
            outcome=SceneOutcome.NO_AND, entities=["ch_lin", "ch_shen", "item_letter"],
            location="loc_cliff", emotion=-1.0,
            state_deltas=[
                StateDelta(entity_id="ch_shen", attribute="allegiance",
                           before="helper", after="opponent")
            ],
            prose=(
                "腰牌落在石头上，声音很脆。\n"
                "林砚没有捡。他看着沈砚，像在看一个刚认识的人。"
            ),
            origin=ChunkOrigin.HUMAN,
            is_branch_point=True,
            storylet_ids=["st_confront", "st_walk_away"],
        ),
        SceneNode(
            id="sc5", title="断云崖·交付",
            focalizer="ch_shen", narrator="ch_lin", focalization=Focalization.INTERNAL,
            fabula_time=TimePoint(day=2, label="日出"), sjuzhet_index=4,
            frequency=Frequency.SINGULATIVE,
            value="信任", value_charge_start="-", value_charge_end="+",
            goal="林砚决定怎么处置密信",
            conflict="他知道交出信就等于承认自己错了",
            turning_point="他把信递了出去 —— 选择相信一次",
            outcome=SceneOutcome.YES_BUT, entities=["ch_lin", "ch_shen", "item_letter"],
            location="loc_cliff", emotion=0.6,
            state_deltas=[
                StateDelta(entity_id="item_letter", attribute="holder",
                           before="ch_lin", after="ch_shen")
            ],
            prose="他把信递过去。风很大，纸角抖了一下，但没有松手。",
            origin=ChunkOrigin.AI_EDITED,
            is_paywall_gate=True,
        ),
    ]

    enigmas = [
        Enigma(
            id="en_who", question="密信是谁放在听雪楼的？",
            planted_at_scene="sc1", state=EnigmaState.RESOLVED,
            revealed_to=["ch_lin", "ch_shen"],
            planned_resolution_scene="sc4", resolved_at_scene="sc4",
            device="草蛇灰线", is_foreshadow=True,
        ),
        Enigma(
            id="en_father", question="父亲当年到底怎么死的？",
            planted_at_scene="sc1", state=EnigmaState.PARTIAL,   # 故意未回收
            revealed_to=["ch_lin"], planned_resolution_scene=None,
            device="草蛇灰线", is_foreshadow=True,
        ),
        Enigma(
            id="en_abandoned", question="客栈老板娘为何提到三十年前的旧案？",
            planted_at_scene="sc2", state=EnigmaState.ABANDONED,  # 故意烂尾
            revealed_to=[], device="略犯", is_foreshadow=True,
        ),
    ]

    facts = [
        KnowledgeFact(id="fact_letter", content="密信的存在",
                      known_by={"ch_lin": 0, "ch_shen": 1}),
        KnowledgeFact(id="fact_betrayal", content="沈砚是锦衣卫",
                      known_by={"ch_lin": 2, "ch_shen": 0}),
    ]

    # --- lore（工业字段体系） ---
    lore_entries = [
        LoreEntry(
            id="lore_setting", keys=["听雪楼", "客栈"], is_constant=True,
            content="听雪楼位于北境边陲，三层木构，冬日雪落即化。",
            position="before_char_defs", order=200, token_budget=120,
        ),
        LoreEntry(
            id="lore_lin", keys=["林砚", "砚儿"], is_constant=True,
            content="林砚，十七岁。偏执、话少、习惯独自承担。语言风格：短句，多反问。",
            position="before_char_defs", order=190, entity_id="ch_lin",
        ),
        LoreEntry(
            id="lore_shen_secret",
            keys=["沈砚"], secondary_keys=["腰牌", "锦衣卫"], logic=KeyLogic.AND_ANY,
            content="沈砚的真实身份是锦衣卫暗桩 —— 此信息在 sc4 之前不得泄露。",
            position="at_depth", depth=2, role="system", order=180,
            recursion=RecursionPolicy(allow_outgoing=True, max_steps=3),
            entity_id="ch_shen",
        ),
        LoreEntry(
            id="lore_court", keys=["锦衣卫", "朝廷"], is_constant=False,
            content="锦衣卫在北境无常驻机构，出现即意味着跨区办案。",
            position="after_char_defs", order=100,
        ),
    ]

    lore = Lorebook()
    for e in lore_entries:
        lore.add(e)

    # --- storylet（2.0 运行时） ---
    # 骨架层与血肉层的接缝：waypoint 门控 storylet，storylet 反过来推进 waypoint。
    # 互斥通过 QBN 的品质机制实现，而不是硬编码分支 —— 这正是 QBN 的要点。
    storylets = [
        # --- sc1：拆信 ---
        Storylet(
            id="st_open_letter", at_waypoint="sc1",
            effects=[QualityEffect(quality="letter_opened", op="set", value=True)],
            salience=0.7, content="他撕开封口。纸边割破了指腹。",
            choices=[Choice(id="c1", text="拆开")],
            advances_waypoint="sc2", repeatable=False,
            arc_weights={"tension": 0.3, "trust": -0.2},
        ),
        Storylet(
            id="st_hesitate", at_waypoint="sc1",
            effects=[QualityEffect(quality="trust", op="add", value=1)],
            salience=0.5, content="他把信推到烛火边，又收了回来。",
            choices=[Choice(id="c2", text="先不动它")],
            advances_waypoint="sc2", repeatable=False,
            arc_weights={"tension": -0.2, "trust": 0.2},
        ),
        # --- sc2：突围 ---
        Storylet(
            id="st_break_out", at_waypoint="sc2",
            effects=[QualityEffect(quality="escaped", op="set", value=True)],
            salience=0.8, content="沈砚挡在他身前，只说了两个字：走。",
            choices=[Choice(id="c3", text="跟着他冲")],
            advances_waypoint="sc3", repeatable=False,
            arc_weights={"tension": 1.0, "trust": 0.5},
        ),
        # --- sc3：静夜（降温段）---
        Storylet(
            id="st_night_talk", at_waypoint="sc3",
            effects=[QualityEffect(quality="trust", op="add", value=1)],
            salience=0.4, content="沈砚替他缠好绷带，手法很稳。",
            choices=[Choice(id="c4", text="问他为什么")],
            advances_waypoint="sc4", repeatable=False,
            arc_weights={"tension": -0.4, "trust": 0.6},
        ),
        # --- sc4：反转（互斥的两块）---
        Storylet(
            id="st_confront", at_waypoint="sc4",
            preconditions=[Condition(quality="confronted", op="==", value=False)],
            effects=[QualityEffect(quality="trust", op="sub", value=2),
                     QualityEffect(quality="confronted", op="set", value=True)],
            salience=0.9, content="「你早就知道。」他把腰牌踢回去。",
            choices=[Choice(id="c5", text="逼他解释")],
            advances_waypoint="sc5", repeatable=False,
            arc_weights={"tension": 0.9, "trust": -0.8},
        ),
        Storylet(
            id="st_walk_away", at_waypoint="sc4",
            preconditions=[Condition(quality="confronted", op="==", value=False)],
            effects=[QualityEffect(quality="trust", op="sub", value=1),
                     QualityEffect(quality="confronted", op="set", value=True)],
            salience=0.6, content="他转身，往崖下走。没有回头。",
            choices=[Choice(id="c6", text="独自离开")],
            advances_waypoint="sc5", repeatable=False,
            arc_weights={"tension": 0.4, "trust": -0.4},
        ),
        # --- sc5：终局 ---
        Storylet(
            id="st_hand_over", at_waypoint="sc5",
            effects=[QualityEffect(quality="ending", op="set", value="trust")],
            salience=0.9, content="他把信递过去。风很大，纸角抖了一下，但没有松手。",
            choices=[Choice(id="c7", text="交出密信")],
            repeatable=False,
            arc_weights={"tension": -0.6, "trust": 1.0},
        ),
        # --- 全局兜底块（硬不变量：永不给玩家零个选项）---
        Storylet(
            id="st_quiet", is_fallback=True, repeatable=True,
            effects=[QualityEffect(quality="turns", op="add", value=1)],
            salience=0.05, content="风穿过崖壁。两人都没有说话。",
            choices=[Choice(id="c8", text="沉默")],
            arc_weights={"tension": 0.0},
        ),
    ]

    return NarrativeIR(
        title="听雪楼",
        medium=Medium.WEB_NOVEL,
        target_length=180000,
        bible=bible,
        plot=plot,
        characters=characters,
        commitment=commitment,
        scenes=scenes,
        enigmas=enigmas,
        facts=facts,
        lore=lore,
        storylets=storylets,
        qualities={"has_letter": True, "trust": 0, "tension": 0.5,
                   "turns": 0, "confronted": False, "letter_opened": False,
                   "escaped": False},
        beat_template="save_the_cat",
        tags=["古风", "悬疑", "双男主"],
    )
