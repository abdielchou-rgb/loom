"""校验器 fixture 库 —— 正例基线 + 反例变异。

**为什么需要这个文件**：在此之前，Loom 的 24 个校验器一个 fixture 都没有。
`scripts/demo.py` 里「健康分 35/100」只证明了校验器**会报警**，
没证明它**报得对**，更没证明它对干净文本**不误报**。
「24 个校验器全绿」是一个没有证据支撑的宣称。

口径（学自 Æsirian `tools/gate_verification/`，但改进了判据）：

    CLEAN 基线   干净 IR 上，每个校验器必须 0 ERROR + 0 WARN（INFO 允许）
                 用「0 严重项」而不是「0 findings」，因为 thread_budget /
                 emotion_curve_match 这类函数在健康时也会输出 INFO 通报。

                 基线用**离线流水线产出**，而不是手搓。手搓的基线会不自觉
                 把校验器的实现细节抄进来，变成「为了通过校验器而写的 IR」。

    反例变异     对每个校验器，注入它**应该抓到**的那一类缺陷
                 断言严重度确实**升级**了（见下）

    净命中       = 变异后严重度 > 基线严重度，且 ≥ 预期严重度
                 **不是**「变异后触发了就算命中」。理由：thread_budget
                 在健康时也输出 INFO，如果只判「有输出」，它永远是命中。
                 用严重度升级才排得掉「对着任何文本都报警」的伪命中。

    报表项       REPORTS 里的函数设计上只做通报（源码里不出现 WARN/ERROR），
                 不参与净命中统计，只断言「基线有输出且不超过 INFO」。

第一次跑这套 fixture 抓到的问题（都已修）：
  1. `li_yu_reduce_threads` 窗口宽 3 而判据是「>3 条」—— 数学上恒为假，
     场景数 < 12 的故事它永远静默通过。
  2. `emotion_curve_match` 只看 Pearson r。一条**没有谷**的单调上升曲线
     与 man_in_a_hole 声明弧线的 r 高达 0.49，被判「匹配度良好」。
  3. STRUCTURE 提示词从不告诉模型声明了哪条弧线，却要求它填 emotion；
     桩件把 emotion 写死成一条与 arc_shape 无关的上升直线 ——
     流水线自己产出的 IR 过不了自己的校验器。
  4. `mirror_bookends` 的文案与判据自相矛盾。

用法：
    python scripts/verify.py          # 跑全部检查
"""

from __future__ import annotations

from copy import deepcopy
from typing import Callable

from loom.ir.enums import (
    ActantRole,
    ArcShape,
    ChunkOrigin,
    EnigmaState,
    Focalization,
    Medium,
    SceneOutcome,
    Severity,
)
from loom.ir.models import (
    ActantBinding,
    NarrativeIR,
    Precondition,
    Provenance,
    Relation,
    StateDelta,
)


# ---------------------------------------------------------------------------
# 干净基线
# ---------------------------------------------------------------------------

_IDEA = "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字"

#: 基线覆盖的媒介。至少要覆盖「小说」和「短剧」两种，
#: 否则 medium:micro_drama 门控的校验器永远处于 SKIPPED 状态 ——
#: 它们的「没问题」是没跑过，不是通过。
BASELINE_MEDIA: tuple[Medium, ...] = (Medium.NOVEL, Medium.MICRO_DRAMA)

_CACHE: dict[Medium, NarrativeIR] = {}


def build_clean_ir(medium: Medium = Medium.NOVEL) -> NarrativeIR:
    """构造一份**结构上无缺陷**的 IR，作为基线。

    用离线流水线产出（而不是手搓），理由见模块 docstring。
    产出后做四处收尾：

      1. 场景 origin 全部设为 HUMAN（否则 provenance_coverage 会因 AI 占比报警）
      2. 补全 provenance 记录（否则同样报警）
      3. 补齐 ①②⑦⑫ 新增的层（lie / 真值层 / 信念层 / 时序边）
      4. 清掉在收尾 1-3 之前算出的提案（它们指向的已经不是当前状态了）

    注意：**情感曲线不再需要收尾**。桩件已经按声明的弧线产出 emotion 值；
    如果还需要在这里补，那说明桩件与声明不一致，应该去修桩件而不是修基线。
    同理，`wound` / `lie` 也不再由这里构造 —— 它们现在由 `CharacterEngine`
    从生成器产出。收尾 3 只**补齐**流水线不该自己发明的东西（秘密 / 关系）。
    """
    if medium in _CACHE:
        return _CACHE[medium]

    from loom.llm import MockGenerator
    from loom.pipeline import LoomPipeline

    ir = LoomPipeline(MockGenerator()).run(
        _IDEA,
        medium=medium,
        arc_shape=ArcShape.MAN_IN_A_HOLE,
        scene_count=6,
        words_per_scene=600,
        max_rounds=0,
    ).ir

    # 收尾 1：人工原创（合规上干净）
    for s in ir.scenes:
        s.origin = ChunkOrigin.HUMAN
        s.model_id = None
        s.prompt_version = None

    # 收尾 2：补全溯源
    ir.provenance = [
        Provenance(
            chunk_id=f"chunk_{s.id}",
            scene_id=s.id,
            origin=ChunkOrigin.HUMAN,
            char_count=len(s.prose or ""),
        )
        for s in ir.scenes
    ]

    # 收尾 3：补齐 ①②⑦⑫ 新增的四层
    _seed_narrative_layers(ir)

    # 收尾 4：清掉在收尾 1-3 **之前**算出的提案。
    #
    # 提案是体检结论的派生品：`critique()` 跑在收尾之前，那时溯源还是全 AI，
    # `provenance_coverage` 会（正确地）报警并因此产出一条提案。收尾把溯源
    # 改成人工原创之后，那条提案的 rationale 已经不成立 —— 留着它就是留一条
    # 指向**过期状态**的待办，而作者会照着它去改一个已经不存在的问题。
    #
    # 干净基线不该有待办：没有结构问题，就没有提案。
    # （反过来说，这也是一条设计约束：提案必须与产出它的那份体检同源。
    #   生产路径上不存在这个问题 —— 那里没有人在体检之后改 IR。）
    ir.proposals = []

    # 收尾 5（P0.5）：让承诺在基线上真正被兑现 —— 否则 commitment_satisfied
    # 会从假门禁变成「对着正常故事也报警」。做法：把未兑现承诺的关键词
    # 注入其 must_hold_at 场景的 goal，使 _commitment_evident 为真。
    from loom.validators.structure import _commitment_evident

    scene_map = {s.id: s for s in ir.scenes}
    for c in ir.commitment.commitments:
        if not _commitment_evident(c, scene_map):
            for sid in c.must_hold_at:
                s = scene_map.get(sid)
                if s is None:
                    continue
                # 注入承诺 statement 的前 20 字到 goal，确保关键词命中
                inject = c.statement[:20] if len(c.statement) <= 20 else c.statement[:20] + "…"
                s.goal = (s.goal or "") + " " + inject
                break  # 只注入第一场即可

    _CACHE[medium] = ir
    return ir


def _seed_narrative_layers(ir: NarrativeIR) -> None:
    """给基线**补齐** ①②⑦⑫ 新增的层：lie / 真值层 / 信念层 / 时序边。

    **为什么必须补**：新门禁的数据需求写在 `REQUIRES` 里，拿不到数据就是
    SKIPPED。若基线不提供这些层，六个新门禁在基线上全部「没跑过」，
    而「没跑过」的「没问题」毫无信息量 —— 这正是本项目反复踩的坑
    （`hook_cadence` / `paywall_gate_present` 就曾因基线只有一种媒介而永远跳过）。

    **本函数现在是「补齐」而不是「构造」**（2026-09-14 改）。在此之前，流水线
    本身不产出 lie / 信念 / 真值，全靠这里手工塞进去 —— 那意味着「基线干净」
    是 fixture 调出来的，不是流水线产出的。现在：
      * `wound` / `lie` 由 `CharacterEngine` 从生成器产出
      * `objective_truth` / `belief_state` / `active_goals` 由 `TensionSeeder` 播种
      * 本函数只补两样**流水线确实不该自己发明**的东西：
        一个作者声明的秘密（`known_secrets`），和两条时序边（`Relation`）。
        秘密必须来自作者，不能从 `wound` 反推 —— 那等于替作者发明一个
        他没声明过的秘密，而 `secret_reveal_ordering` 会因此报出他无法理解的 WARN。
        关系同理：谁和谁是什么关系，是创作内容。

    因此本函数**幂等且不覆盖**已有数据：作者/流水线给的值优先。
    若补完还报警，要么判据不对、要么基线本身有问题 —— 两种都要查，
    不能靠「把基线调绿」蒙混过去。这里的做法是让 lie / secret 的文本
    与后半程场景的结构字段**天然重叠**（基线是一个「锚被兑现了」的故事），
    而不是放宽门禁判据。
    """
    from loom.ir.tom import Belief, BeliefSource, CharacterBeliefState

    scenes = ir.ordered_scenes()
    if not scenes:
        return
    late = scenes[int(len(scenes) * 0.6) :] or scenes[-1:]
    anchor = late[-1]

    # ⑦ lie / wound：只在流水线没给的时候兜底。
    #    兜底的 lie 里包含 anchor 的 value，于是字符二元组必然与
    #    「后半程结构文本」重叠 —— 即 lie 被触及了。
    for ch in ir.characters.characters.values():
        if not ch.wound:
            ch.wound = f"{ch.name}曾被最信任的人抛下"
        if not ch.lie:
            ch.lie = f"我只要守住{anchor.value}就够了"

    # ② 真值层：**追加**，不重建（TensionSeeder 已经写过 lie 那几条）。
    protagonist = next(iter(ir.characters.characters.values()), None)
    if protagonist is None:
        return
    prop = f"{anchor.value}是否值得"
    ir.objective_truth.setdefault(prop, "值得")
    secret_prop = f"{anchor.value}的来历"
    ir.objective_truth.setdefault(secret_prop, "与主角有关")

    # ② 信念层：与已有信念**合并**（TensionSeeder 播下的 lie 信念必须留住，
    #    否则「基线有张力点」这件事又变回 fixture 手工构造的了）。
    bs = protagonist.belief_state or CharacterBeliefState()
    bs.world_beliefs.setdefault(
        prop,
        Belief(
            proposition=prop,
            value="值得",  # 与真值一致 -> belief_consistency 不报
            confidence=0.9,
            source=BeliefSource.WITNESSED,
        ),
    )
    bs.known_secrets = sorted({*bs.known_secrets, secret_prop})
    protagonist.belief_state = bs

    # ⑫ 时序边：一条无界、一条有界，且 kind 不同 ——
    #    验证「不同 kind 的区间重叠是合法的」这条判据。
    #    仅在流水线没产出关系时兜底（关系是创作内容，不该被 fixture 覆盖）。
    counterpart = next(
        (c for c in ir.characters.characters.values() if c.id != protagonist.id), None
    )
    if counterpart is not None and not ir.bible.relations:
        ir.bible.relations = [
            Relation(src=protagonist.id, dst=counterpart.id, kind="旧识"),
            Relation(
                src=protagonist.id,
                dst=counterpart.id,
                kind="对峙",
                valid_from_day=anchor.fabula_time.day,
            ),
        ]


# ---------------------------------------------------------------------------
# 反例变异
# ---------------------------------------------------------------------------

#: code -> (变异函数, 预期严重度)。变异就地修改 IR。
MUTATIONS: dict[str, tuple[Callable[[NarrativeIR], None], Severity]] = {}


def mutation(code: str, expected: Severity = Severity.WARN):
    def deco(fn: Callable[[NarrativeIR], None]):
        MUTATIONS[code] = (fn, expected)
        return fn

    return deco


# -- structure --------------------------------------------------------------


@mutation("value_charge_flip")
def _m_value_flip(ir: NarrativeIR) -> None:
    """把一场的价值极性抹平 —— McKee：场景结束时价值必须改变。"""
    s = ir.ordered_scenes()[1]
    s.value_charge_end = s.value_charge_start


@mutation("state_delta")
def _m_state_delta(ir: NarrativeIR) -> None:
    """清空一场的状态增量 —— Todorov：零增量场景不成立。"""
    ir.ordered_scenes()[2].state_deltas = []


@mutation("commitment_satisfied", Severity.ERROR)
def _m_commitment(ir: NarrativeIR) -> None:
    """让一条硬承诺既未兑现、也无落点。"""
    c = ir.commitment.commitments[0]
    c.satisfied = False
    c.must_hold_at = []


@mutation("enigma_resolution", Severity.ERROR)
def _m_enigma_abandoned(ir: NarrativeIR) -> None:
    """遗弃一个谜题 —— Barthes 阐释符码：悬空未解是烂尾信号。"""
    ir.enigmas[0].state = EnigmaState.ABANDONED
    ir.enigmas[0].resolved_at_scene = None


@mutation("mirror_bookends", Severity.INFO)
def _m_mirror(ir: NarrativeIR) -> None:
    """让首尾状态完全同形 —— 净变化为零。"""
    scenes = ir.ordered_scenes()
    first, last = scenes[0], scenes[-1]
    last.value = first.value
    last.value_charge_end = first.value_charge_start


@mutation("emotion_curve_match")
def _m_emotion(ir: NarrativeIR) -> None:
    """把情感曲线换成声明弧线的**反面**。

    基线声明 man_in_a_hole（先跌后起，谷底在 42%）。这里注入的是一条
    「先起后跌」的曲线：它**有**转折点，但类型错了（峰 vs 谷），
    且整体相关度为 -1.00。

    为什么不用「单调下降」当反例：单调曲线与 man_in_a_hole 的
    Pearson r 只有 -0.50，能触发；但它在旧实现（只看 r）下也只在
    r < 0.3 时才触发 —— 而**单调上升**的 r 是 +0.49，旧实现会放行。
    所以这里选「有转折点但转错方向」，它同时压住两条判据。
    """
    scenes = ir.ordered_scenes()
    anti = [0.0, 0.5, 0.95, 0.5, -0.05, -0.6]
    for s, v in zip(scenes, anti):
        s.emotion = v


@mutation("li_yu_main_brain")
def _m_free_scene(ir: NarrativeIR) -> None:
    """造一个既无承诺承载、也无对应事件的游离场次。"""
    target = ir.ordered_scenes()[-2].id
    for c in ir.commitment.commitments:
        c.must_hold_at = [x for x in c.must_hold_at if x != target]
    ir.plot.events = {
        k: v for k, v in ir.plot.events.items() if v.scene_id != target
    }


@mutation("li_yu_reduce_threads")
def _m_threads(ir: NarrativeIR) -> None:
    """在一个窗口内塞进 4 条并发支线 —— 李渔「减头绪」。

    基线只有 3 条价值线（信任/代价/真相循环），任何窗口都 ≤3。
    这里把前 4 场改成 4 条互不相同的支线。
    """
    scenes = ir.ordered_scenes()
    for i, s in enumerate(scenes[:4]):
        s.value = f"支线{i + 1}"


@mutation("mao_repeat_variation")
def _m_repeat(ir: NarrativeIR) -> None:
    """把两场做成完全同质 —— 毛宗岗「犯而不犯」的反面。"""
    scenes = ir.ordered_scenes()
    a, b = scenes[1], scenes[3]
    b.turning_point = a.turning_point
    b.outcome = a.outcome
    b.value = a.value
    b.value_charge_start = a.value_charge_start


@mutation("actant_collision")
def _m_actant(ir: NarrativeIR) -> None:
    """同时压住两条分支：

      * 主角兼 OPPONENT —— Greimas「一人占两位」的反转信号（INFO）
      * 同伴占 4 个行动元 —— 角色功能过载（WARN）

    两条分支是 if/elif，互斥，所以只注入一种永远测不到另一种。
    """
    scenes = ir.ordered_scenes()
    hero = scenes[0].focalizer  # 基线里已是 SUBJECT + SENDER + RECEIVER
    ir.characters.actants.append(
        ActantBinding(role=ActantRole.OPPONENT, entity_id=hero)
    )
    mate = next(c for c in ir.characters.characters if c != hero)
    for role in (ActantRole.SENDER, ActantRole.RECEIVER):
        ir.characters.actants.append(
            ActantBinding(role=role, entity_id=mate)
        )


@mutation("focalizer_boundary", Severity.ERROR)
def _m_focalizer(ir: NarrativeIR) -> None:
    """内聚焦越界：聚焦者揭示了谜题，但他并不知情。"""
    s = ir.ordered_scenes()[3]
    s.focalization = Focalization.INTERNAL
    e = ir.enigmas[0]
    e.resolved_at_scene = s.id
    e.revealed_to = [
        c for c in e.revealed_to if c != s.focalizer
    ] or ["__nobody__"]
    # __nobody__ 不存在 → 同时触发 knowledge_matrix，这是可接受的耦合


@mutation("causal_chain_integrity", Severity.ERROR)
def _m_causal(ir: NarrativeIR) -> None:
    """引用一个不存在的前置事件。"""
    ev = next(iter(ir.plot.events.values()))
    ev.preconditions.append(
        Precondition(kind="prior_event", target="ev_不存在的事件")
    )


@mutation("hook_cadence")
def _m_hook(ir: NarrativeIR) -> None:
    """短剧 + 集末无钩子（既无翻转、也无新谜题、也非分支点）。

    基线是 NOVEL，这个校验器被 SKIPPED；变异把媒介切成短剧，
    于是基线（短剧版）与变异版是同一媒介下的对比。
    """
    ir.medium = Medium.MICRO_DRAMA
    s = ir.ordered_scenes()[2]
    s.value_charge_end = s.value_charge_start
    ir.enigmas = [e for e in ir.enigmas if e.planted_at_scene != s.id]
    s.is_branch_point = False


@mutation("paywall_gate_present", Severity.ERROR)
def _m_paywall(ir: NarrativeIR) -> None:
    """短剧不标付费卡点（基线在正中间一场标了）。"""
    ir.medium = Medium.MICRO_DRAMA
    for s in ir.scenes:
        s.is_paywall_gate = False


@mutation("template_coverage", Severity.ERROR)
def _m_template(ir: NarrativeIR) -> None:
    """声明一个不存在的结构模板。"""
    ir.beat_template = "__不存在的模板__"


@mutation("outcome_distribution")
def _m_outcome(ir: NarrativeIR) -> None:
    """所有场景都是 YES —— 冲突强度不足。"""
    for s in ir.scenes:
        s.outcome = SceneOutcome.YES


@mutation("premise_fidelity")
def _m_premise(ir: NarrativeIR) -> None:
    """让结局与承诺层**同时**与前提失锚 —— 前提漂移。

    依据：PLOTTER（ACL 2026 Findings）实测图规划在 Premise Fidelity 上
    只有 40% / 14% / 44% 的胜率，**图的迭代精炼会偏离原初前提**。
    Loom 走的是同一条路线（`CriticLoop` 迭代修订），所以这条必须有反例。

    两处一起打，是因为判据本来就是「两处**同时**失锚才 WARN」：
    只改一处只会得到 INFO，升不到 WARN —— 那正是这个 fixture 要区分的东西。
    """
    # 与前提**零**词汇交集的替换文本（中文 2-gram 与英文词都不重叠）
    filler = "锅炉压力表读数持续攀升，值班员抄表后锁上铁柜。"
    for s in ir.ordered_scenes()[-2:]:
        s.prose = filler
        s.turning_point = "仪表盘指针越过红线"
    for c in ir.commitment.commitments:
        c.statement = "档案编号必须完整登记"


@mutation("desire_need_conflict")
def _m_desire_need(ir: NarrativeIR) -> None:
    """把角色的 `need` 改成与 `want` **完全相同** —— 取消内在冲突。

    依据：Truby《故事写作大师班》（豆瓣 8.7）的核心断言是
    **欲望与需求必须冲突**。想要 = 需要 时，故事退化成一条障碍赛道：
    角色一路打怪拿到 X，内在毫发无损。

    这个变异之所以必要，是因为 `want` / `need` 两个字段**早就存在于 IR**，
    提示词也一直在生成，但此前没有任何校验器读它们 ——
    一个没人读的字段写错也永远不会被发现。反例把它钉住。

    注：只改 need、不动 want，模拟的是「写到一半把需求写成了欲望的复述」，
    这是真实写作里最常见的形式（不是凭空造一个畸形 IR）。
    """
    for ch in ir.characters.characters.values():
        if (ch.want or "").strip():
            ch.need = ch.want
            break


@mutation("state_transition_integrity", Severity.ERROR)
def _m_state_transition(ir: NarrativeIR) -> None:
    """在 sc3 让某角色「死亡」（delta `after="dead"` 且 `forbidden=["alive"]`），
    却在其后的场景（收尾场）又把它放回 focalizer / 出场实体 —— 即「死人复活」。

    依据：ConWriter (EMNLP 2026, arXiv:2608.05169) 用 (Pre, Post, Forbidden)
    三元组做符号化一致性验证；`forbidden` 显式落成 `StateDelta.forbidden` 后，
    跨场追问「禁忌态是否被后续场景复现」才能成立。Todorov (1977) 叙事转化态
    也要求沿话语顺序维护实体累计状态。

    这是真实写作里最常见的「连续性崩坏」形态之一：作者在前一场写死了人，
    后一场忘了，又让他说话 / 出场。单场景校验器看不到，必须跨场。
    """
    scenes = ir.ordered_scenes()
    if len(scenes) < 3:
        return
    hero = next(iter(ir.characters.characters.values()))
    scenes[2].state_deltas = list(scenes[2].state_deltas) + [
        StateDelta(
            entity_id=hero.id,
            attribute="status",
            before="alive",
            after="dead",
            forbidden=["alive"],
        )
    ]
    last = scenes[-1]
    last.focalizer = hero.id
    if hero.id not in last.entities:
        last.entities = list(last.entities) + [hero.id]


@mutation("branch_consistency", Severity.ERROR)
def _m_branch_consistency(ir: NarrativeIR) -> None:
    """在 IR 上挂两条分叉分支：分支 A 让主角「活着」，分支 B 让同一主角「死亡」。

    依据：Emily Short《Beyond Branching》(2016) —— 从同一故事点分叉出的
    可能世界共享该点的全部事实；若两分支对同一实体设了互斥状态，读者走完
    两条线会抓到吃书。本变异是互动叙事（Ink / Ren'Py）最核心的结构缺陷形态。
    """
    from loom.validators.branches import Branch, attach_branches

    if not ir.characters.characters:
        return
    hero = next(iter(ir.characters.characters.values()))
    attach_branches(
        ir,
        [
            Branch(
                id="branch_a",
                parent_point="root",
                entity_states={hero.id: {"status": "alive"}},
            ),
            Branch(
                id="branch_b",
                parent_point="root",
                entity_states={hero.id: {"status": "dead"}},
            ),
        ],
    )


# -- consistency ------------------------------------------------------------


@mutation("knowledge_matrix", Severity.ERROR)
def _m_knowledge(ir: NarrativeIR) -> None:
    """谜题的知情者引用不存在的角色。"""
    ir.enigmas[0].revealed_to = ["__不存在的人__"]


@mutation("revelation_regression", Severity.INFO)
def _m_revelation(ir: NarrativeIR) -> None:
    """把 4 条谜题动作压到同一场。"""
    s = ir.ordered_scenes()[2]
    for i, e in enumerate(ir.enigmas[:4]):
        e.planted_at_scene = s.id
        e.resolved_at_scene = s.id if i % 2 else None


@mutation("timeline_monotonic")
def _m_timeline(ir: NarrativeIR) -> None:
    """非倒错的场景之间，故事时间逆序。

    先把所有时间点整体后移，再让最后一场回退一天 —— 直接减会撞上
    `day >= 0` 的模型约束（第一次跑就是在这里崩的）。
    """
    scenes = ir.ordered_scenes()
    for s in scenes:
        s.fabula_time.day += 10
    scenes[-1].fabula_time.day = scenes[-2].fabula_time.day - 1


@mutation("entity_reference", Severity.ERROR)
def _m_entity(ir: NarrativeIR) -> None:
    """场景引用未登记的实体。"""
    ir.ordered_scenes()[1].entities.append("__未登记的实体__")


@mutation("alias_collision", Severity.ERROR)
def _m_alias(ir: NarrativeIR) -> None:
    """两个实体共用别名 —— 吃书根源。"""
    chars = list(ir.characters.characters.values())
    if len(chars) >= 2:
        chars[1].aliases = [chars[0].name]
    else:
        ir.bible.entities["__dup__"].aliases = [chars[0].name]


@mutation("world_rule_violation")
def _m_world_rule(ir: NarrativeIR) -> None:
    """把所有世界规则降级为软设定 —— 无从判定崩坏。

    注：这条变异测的是「没有硬规则时会不会报警」。
    真正的**语义**违规检测需要理解，纯规则做不到。fixture 只覆盖边界。
    """
    for r in ir.bible.rules:
        r.is_hard = False


@mutation("numeric_fact_consistency")
def _m_numeric(ir: NarrativeIR) -> None:
    """同一主体、同一动作、同一单位，两个场景给了不同的值。

    基线正文是抒情的，一个数字都没有 —— 所以这里必须**注入**矛盾，
    而不是指望流水线自己产出。用角色的显示名当主体：
    校验器只认已登记的名字（代词主体无法跨场对齐，见 csn.py 的局限说明）。
    """
    scenes = ir.ordered_scenes()
    name = next(iter(ir.characters.characters.values())).name
    scenes[0].prose = (scenes[0].prose or "") + f"\n{name}在崖下等了三十年。"
    scenes[2].prose = (scenes[2].prose or "") + f"\n{name}在崖下等了四十年。"


@mutation("provenance_coverage")
def _m_provenance(ir: NarrativeIR) -> None:
    """清空溯源 —— 合规报告将无法生成。"""
    ir.provenance = []
    for s in ir.scenes:
        s.origin = ChunkOrigin.AI_GENERATED
        s.model_id = "mock-deterministic-v1"


# ---------------------------------------------------------------------------
# ①②⑦⑫ 新增门禁的反例
# ---------------------------------------------------------------------------


@mutation("pattern_saturation")
def _m_pattern(ir: NarrativeIR) -> None:
    """连续 5 场都用同一个工艺装置（「打脸」）。

    基线是干净的：装置分散，`check_saturation` 零输出。这里把最后 5 场的
    `value` 全改成同一个爽感装置名，于是窗口内频率 = 5/5 = 1.0 ≥ 0.8。
    """
    for s in ir.ordered_scenes()[-5:]:
        s.value = "打脸"


@mutation("declaration_consistency")
def _m_declaration(ir: NarrativeIR) -> None:
    """自申报**虚报**：声明了一个场景卡里根本没有的变化。

    这正是 CHANGES 协议要防的形态 —— 模型用一份漂亮的声明骗过门禁。
    虚报定为 WARN（而漏报只是 INFO），严重度刻意不对称。
    """
    s = ir.ordered_scenes()[0]
    declared = dict(s.declared)
    declared["character_state"] = list(declared.get("character_state", [])) + [
        {"entity": "__不存在的角色__", "attribute": "不存在的属性", "after": True}
    ]
    s.declared = declared


@mutation("need_revelation_at_climax")
def _m_need(ir: NarrativeIR) -> None:
    """把角色的 `need` 换成与高潮段结构文本**零字面重叠**的措辞。

    判据是字符二元组重叠，所以这里要确保新 need 的所有二元组都不出现在
    高潮段的 turning_point / conflict / value / goal / outcome 里。
    用无意义的音节串是刻意的 —— 保证零重叠，不依赖对中文词表的猜测。

    与 `_m_lie` 的区别：那个改的是 lie（假命题），这个改的是 need（真需求）。
    两者都该在高潮被处理，但**方向相反**（lie 要被打破，need 要被兑现），
    所以是两个独立的反例，不能共用。
    """
    ch = next(iter(ir.characters.characters.values()))
    ch.need = "呜哇呀哈嘿噜"


@mutation("prose_structure_fidelity", Severity.INFO)
def _m_prose_structure(ir: NarrativeIR) -> None:
    """让某一场的正文与它自己声明的转折点/冲突**零词汇交集**。

    依据：Fan 等 *Hierarchical Neural Story Generation*（ACL 2018，1151 次引用）
    的核心主张是分层：高层规划（premise/outline）约束低层实现（句子）。
    反过来就是可校验的失败模式 —— **低层跑出高层之外**。

    只改一场，不改全部：分层生成的问题总是**局部**的，
    整篇平均会稀释掉单场的崩坏（5 场里 1 场跑题，平均值仍好看）。
    这一条也是本校验器按场报告、不按篇报告的原因。
    """
    scenes = ir.ordered_scenes()
    if not scenes:
        return
    s = scenes[len(scenes) // 2]
    s.prose = "锅炉压力表读数持续攀升，值班员抄表后锁上铁柜。"


@mutation("lie_arc_closure")
def _m_lie(ir: NarrativeIR) -> None:
    """把角色的 lie 换成一个与后半程结构文本**毫无字面重叠**的命题。

    判据是字符二元组重叠，故这里要确保新 lie 的所有二元组都不出现在
    后半程的 turning_point / conflict / value / goal 里。
    """
    ch = next(iter(ir.characters.characters.values()))
    ch.lie = "呜哇呀哈嘿噜"


@mutation("drift_guard")
def _m_drift_padding(ir: NarrativeIR) -> None:
    """尾窗原地踏步 —— 自动驾驶长跑的头号失败模式（注水）。

    `drift_guard` 是唯一一个**全局**判据：其余校验器都是逐场局部检查，
    只有它问「这一整段跑下来到底推进了没有」。它的 padding 判据是
    尾窗既无新的 `(entity, attribute)` 状态键、也无新的价值极性转移。

    这里把尾窗的状态增量清空、价值极性抹平，于是「写了很多场，
    什么都没推进」—— 正是它要抓的东西，也正是「每段都合理、
    合起来什么都不证明」这个失败模式在长跑里的具体形态。
    """
    scenes = ir.ordered_scenes()
    # drift 自己的窗口是 max(3, n//3)，取后一半足以覆盖它。
    for s in scenes[max(1, len(scenes) // 2) :]:
        s.state_deltas = []
        s.value_charge_end = s.value_charge_start


@mutation("belief_consistency")
def _m_belief(ir: NarrativeIR) -> None:
    """角色的信念与客观真值不一致，却没有标成错误信念。

    这是更危险的形态：模型以为角色知道真相，其实不知道 ——
    于是本该生成的张力（戏剧反讽）不会被生成。
    """
    ch = next(
        (c for c in ir.characters.characters.values() if c.belief_state is not None),
        None,
    )
    if ch is None:
        return
    for belief in ch.belief_state.world_beliefs.values():
        belief.value = "__与真值不一致的值__"


@mutation("secret_reveal_ordering")
def _m_secret(ir: NarrativeIR) -> None:
    """秘密埋了但从未被任何场景触及（埋而不揭）。"""
    ch = next(
        (c for c in ir.characters.characters.values() if c.belief_state is not None),
        None,
    )
    if ch is None:
        return
    ch.belief_state.known_secrets = ["呜哇呀哈嘿噜"]


@mutation("relation_temporal", Severity.ERROR)
def _m_relation(ir: NarrativeIR) -> None:
    """关系区间倒置：30 天开始、10 天结束。

    任何时间查询都会得到「从未有效」这种无意义结果，属硬数据错误。
    """
    chars = list(ir.characters.characters.values())
    if len(chars) < 2:
        return
    ir.bible.relations.append(
        Relation(
            src=chars[0].id,
            dst=chars[1].id,
            kind="倒置区间",
            valid_from_day=30,
            valid_to_day=10,
        )
    )


# ---------------------------------------------------------------------------
# 平台合规向（compliance.py）的反例
#
# 这三项是**报表项**（在 base.REPORTS 里），因此不参与净命中统计 ——
# 净命中判的是「严重度升级」，而报表项按设计只出 INFO，永远升不了级。
# 它们的反例有另一个用途：证明自己**不是空转**。
#
# 注意与门禁项的区别（这是 `base.ADVISORY_DEFECT` 存在的理由）：
# 门禁项证明自己「抓得住缺陷」；缺陷型报表项证明自己「说得出来」——
# 因为对缺陷型检测器来说，在干净稿子上沉默是**正确结果**，
# 用「基线必须有输出」去要求它，等于逼它对干净稿子硬报假阳性。
# ---------------------------------------------------------------------------

#: 等长句。重复它会同时让「句长分布」与「场长分布」都塌到完全均匀。
_UNIFORM_UNIT = "他走进院子，停了一下，又往前走了两步。"


@mutation("length_burstiness", Severity.INFO)
def _m_burstiness(ir: NarrativeIR) -> None:
    """把每一场的正文换成**同样长度**的等长句。

    两个轴一起塌：场长全部相等（偏离 0%，番茄的 ±5% 口径），
    句长全部相等（爆发度 B = −1，Goh & Barabási 的下界）。
    单改一个轴不足以证明两个判据都活着 —— 本 fixture 一次打两边。
    """
    for s in ir.ordered_scenes():
        s.prose = _UNIFORM_UNIT * 6


@mutation("adverb_density", Severity.INFO)
def _m_adverb(ir: NarrativeIR) -> None:
    """一段里塞 6 个高频副词 —— 番茄的口径是「超过 4 次」。

    用 6 而不是 5，是为了离阈值远一格：正好卡在 5 的 fixture
    在有人微调阈值时会静默失效，而失效的 fixture 比没有 fixture 更糟
    （它还在报告里显示成「有反例」）。
    """
    ir.ordered_scenes()[0].prose = (
        ir.ordered_scenes()[0].prose or ""
    ) + "\n他极其愤怒，异常冷静，十分缓慢，格外小心，无比沉默，尤为警惕。"


@mutation("dialogue_rhythm", Severity.INFO)
def _m_dialogue(ir: NarrativeIR) -> None:
    """六轮纯对白，一问一答，中间没有任何叙述，全篇无打断标记。

    基线正文**一个引号都没有**（桩件不写对白），所以这里必须注入 ——
    否则 `dialogue_rhythm` 会因为没有对话而 SKIPPED，
    而「SKIPPED」与「通过」在同一份报告里看起来一模一样。
    """
    ir.ordered_scenes()[0].prose = (ir.ordered_scenes()[0].prose or "") + (
        "\n「你来了？」\n「来了。」\n「东西呢？」\n「在这儿。」\n"
        "「确定？」\n「确定。」"
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def clean_copy(medium: Medium = Medium.NOVEL) -> NarrativeIR:
    """每次变异都在干净基线的深拷贝上做，保证 fixture 之间互不污染。"""
    return deepcopy(build_clean_ir(medium))


def has_severe(findings: list, min_sev: Severity = Severity.WARN) -> bool:
    order = {Severity.INFO: 0, Severity.WARN: 1, Severity.ERROR: 2}
    return any(order[f.severity] >= order[min_sev] for f in findings)
