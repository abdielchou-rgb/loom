"""叙事层校验器 —— 依赖 ①②⑦⑫ 新增的 IR 层。

与 `structure.py` / `consistency.py` 的分工：那两个模块查的是**经典结构**
（McKee / Todorov / Genette / 李渔 / 毛宗岗）与**一致性**（时间线 / 实体 / 世界规则）。
本模块查的是**新加的三层**：

    declaration_consistency    ① CHANGES 自申报协议 —— 「结构说 A、正文写 B」
    lie_arc_closure            ⑦ 四卡锚 —— 高潮有没有真的处理那个 lie
    belief_consistency         ② ToM —— 信念标注与客观真值是否自洽
    dramatic_irony_available   ② ToM —— 可用反讽点（**报表项，不是门禁**）
    secret_reveal_ordering     ② ToM —— 埋下的秘密有没有揭示
    relation_temporal          ⑫ 时序边 —— 关系的有效期是否合法

**为什么单独一个模块而不是塞进 consistency.py**：
`consistency.py` 的 8 个校验器全部只依赖「经典」IR 字段，任何 IR 都能跑。
本模块的校验器依赖新增的可选字段（`declared` / `lie` / `belief_state` /
`objective_truth` / `valid_from_day`），**没有这些字段时应当 SKIPPED 而不是 PASS**。
把它们混在一起会让 `REQUIRES` 表的语义变糊：一个模块内的校验器数据需求
差别越大，越难一眼看出「这批检查到底依赖什么」。
"""

from __future__ import annotations

from ..ir.enums import EnigmaState, Severity
from ..ir.models import NarrativeIR
from ..ir.tom import find_dramatic_irony
from .base import Finding, register

# ---------------------------------------------------------------------------
# ① CHANGES 自申报协议
# ---------------------------------------------------------------------------


def _delta_keys(ir: NarrativeIR, scene) -> set[tuple[str, str]]:
    """场景卡声称的变化：`(实体 id, 属性)`。"""
    return {(d.entity_id, d.attribute) for d in scene.state_deltas}


def _declared_keys(scene) -> set[tuple[str, str]]:
    """声明里申报的 `character_state` 变化：`(实体, 属性)`。"""
    out: set[tuple[str, str]] = set()
    for item in scene.declared.get("character_state", []) or []:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity") or item.get("entity_id") or item.get("who")
        attr = item.get("attribute") or item.get("field")
        if entity and attr:
            out.add((str(entity), str(attr)))
    return out


@register("declaration_consistency")
def declaration_consistency(ir: NarrativeIR) -> list[Finding]:
    """① 自申报与场景卡的一致性 —— 补上「说一套写一套」的漂移缺口。

    **这是本模块最重要的一条。** Keel 的 `StructureEngine` 在场景卡层产出
    `state_deltas`，`Scripter` 据此写正文 —— 但原先**没有任何机制检查正文
    是否真的做了场景卡说的那件事**。结果是「结构体检 92 分，正文一场都没兑现」
    可以同时成立。CHANGES 协议让模型自证，本校验器核对这份自证。

    双通道原则（安全阀）：**声明只是提示通道，IR 才是真值通道。**
    因此这里比对的是「声明 vs 场景卡」，而不是「声明 vs 正文」——
    正文的语义提取是另一条更贵的通道，且容易误判。

    两类偏差的严重度刻意不对称：

      * **虚报**（声明了场景卡没有的变化）= WARN —— 模型在编造「我改了什么」，
        这正是要防的（用漂亮声明骗过门禁）。
      * **漏报**（场景卡有变化但没申报）= INFO —— 只是自证不完整，
        不构成欺骗，且可能是模型没看见。宁可漏报不要虚报，是协议本身
        给模型的指令，因此漏报更可容忍。

    无声明 = 降级（不是失败）—— 由 `REQUIRES` 把它标成 SKIPPED，不进健康分。
    """
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.declared:
            continue
        want = _delta_keys(ir, s)
        got = _declared_keys(s)

        for entity, attr in sorted(got - want):
            out.append(
                Finding(
                    code="declaration_consistency",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message=f"自申报虚报：声明了 {entity}.{attr} 的变化，但场景卡没有这个变化",
                    suggestion=(
                        "声明与场景卡矛盾时以场景卡为准。让模型只申报正文里"
                        "真的写了的变化，宁可少报也不要虚报"
                    ),
                    evidence={"entity": entity, "attribute": attr, "kind": "over_declared"},
                )
            )

        for entity, attr in sorted(want - got):
            out.append(
                Finding(
                    code="declaration_consistency",
                    severity=Severity.INFO,
                    scene_id=s.id,
                    message=f"自申报漏报：场景卡声称 {entity}.{attr} 变化，但声明里没有",
                    suggestion="自证不完整。若正文确实没写这个变化，问题在正文而非声明",
                    evidence={"entity": entity, "attribute": attr, "kind": "under_declared"},
                )
            )
    return out


# ---------------------------------------------------------------------------
# ⑦ 四卡锚
# ---------------------------------------------------------------------------


def _shingles(text: str, n: int = 2) -> set[str]:
    """字符 n-gram。中文没有词边界，字符二元组是最省事且零依赖的近似。"""
    t = "".join(ch for ch in text if not ch.isspace())
    return {t[i : i + n] for i in range(len(t) - n + 1)} if len(t) >= n else set()


@register("desire_need_conflict")
def desire_need_conflict(ir: NarrativeIR) -> list[Finding]:
    """欲望与需求是否**真的不同** —— 角色有没有内在冲突。

    出处：John Truby《The Anatomy of Story》(2007)，中文版《故事写作大师班》
    （豆瓣 8.7）。Truby 的四元：

        弱点 weakness → 欲望 desire（有意识的目标）→ 需求 need（无意识的必需）
        → 自我启示 self-revelation

    核心断言：**欲望与需求必须相互冲突**。角色「想要的」和「真正需要的」
    如果是同一件事，那故事就不是道德论证，只是一条障碍赛道 ——
    角色一路打怪拿到 X，内在毫发无损。这是角色弧线最常见、也最难自查的失败模式，
    因为它写起来**非常顺**（没有内在阻力）。

    为什么值得单独立一个校验器：IR 里 `Character.want` / `Character.need`
    **早就存在**，提示词（engines.py）也一直在生成它们，
    但此前**没有任何校验器读这两个字段** —— 这正是本项目反复出现的
    「有数据、没判据」型缺口。本校验器不新增任何 schema。

    判据：字符二元组重叠率 `|want ∩ need| / min(|want|, |need|)`。
    完全相同（归一化后）或重叠 ≥ 0.5 ⇒ 判定为「想要的就是需要的」。
    用 min 做分母而不是并集，是因为两个长度差很大的短句
    （如「查清真相」vs「学会把真相交给别人并承担后果」）用 Jaccard 会稀释掉。

    局限（写出来，不藏着）：字面重叠，认不出「同义改写」。
    「想要赢」与「需要学会认输」在字面上是冲突的但本校验器看不出来 ——
    它只能抓「用不同措辞说同一件事」和「完全复制粘贴」这两类。
    """
    out: list[Finding] = []
    for ch in ir.characters.characters.values():
        want = "".join((ch.want or "").split())
        need = "".join((ch.need or "").split())
        if not want or not need:
            continue  # 缺字段是**这个角色**不可评估，不是全剧的问题

        if want == need:
            out.append(
                Finding(
                    code="desire_need_conflict",
                    severity=Severity.WARN,
                    message=(
                        f"角色「{ch.name}」的欲望与需求是同一句话（{want}）—— "
                        "角色没有内在冲突"
                    ),
                    suggestion=(
                        "Truby：欲望是角色**以为**自己要的，需求是他**真正**需要的，"
                        "两者必须冲突 —— 让追求欲望的过程反过来逼他面对需求。"
                        "想要 = 需要 意味着故事只是一条障碍赛道，不是道德论证"
                    ),
                    evidence={
                        "character": ch.name,
                        "want": ch.want,
                        "need": ch.need,
                        "overlap": 1.0,
                        "limitation": "字面判据：认不出同义改写，只能抓复制与近义重复",
                    },
                )
            )
            continue

        w_grams, n_grams = _shingles(want), _shingles(need)
        if not w_grams or not n_grams:
            continue
        overlap = len(w_grams & n_grams) / min(len(w_grams), len(n_grams))
        if overlap >= 0.5:
            out.append(
                Finding(
                    code="desire_need_conflict",
                    severity=Severity.WARN,
                    message=(
                        f"角色「{ch.name}」的欲望（{ch.want}）与需求（{ch.need}）"
                        f"用词重合 {overlap:.0%} —— 疑似说的是同一件事"
                    ),
                    suggestion=(
                        "把需求改成**与欲望相反**的东西：欲望是向外索取，"
                        "需求通常是向内放弃（学会信任 / 学会放手 / 承认软弱）"
                    ),
                    evidence={
                        "character": ch.name,
                        "want": ch.want,
                        "need": ch.need,
                        "overlap": round(overlap, 3),
                        "limitation": "字面判据：认不出同义改写，只能抓复制与近义重复",
                    },
                )
            )
    return out


@register("prose_structure_fidelity")
def prose_structure_fidelity(ir: NarrativeIR) -> list[Finding]:
    """正文有没有兑现**这一场**声明的结构（转折点 / 冲突）。

    出处：Fan, Lewis & Dauphin, *Hierarchical Neural Story Generation*
    (ACL 2018，**本清单中引用数最高的论文，1151 次**)。
    该文的核心主张是**分层**：先有高层规划（premise / outline），
    再生成低层实现（句子）。它之所以比端到端生成更连贯，
    正是因为**低层被高层约束着**。

    反过来说就是一条可校验的失败模式：**低层跑出高层之外**。
    Keel 的 IR 恰好就是这个分层的显式版本 ——
    `SceneNode.turning_point` / `conflict` 是高层规划，`prose` 是低层实现。
    所以这条判据在 Keel 上是**直接可测的**，不必再训一个模型。

    判据：单场 `prose` 与该场声明的 `turning_point`+`conflict` 做字符二元组重叠。
    零重叠 = 这一场的正文与它的结构声明**毫无关系** → 低层跑题。

    为什么按场报而不是整篇报：整篇平均会稀释掉单场的崩坏
    （5 场里 1 场跑题，平均值仍然好看）。分层生成的问题总是**局部**的。

    局限：字面重叠。用完全不同的措辞写同一个转折会被误报为跑题，
    故严重度取 INFO（通报），不取 WARN —— 它是**可疑信号**，不是确定的缺陷。
    """
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        prose = (s.prose or "").strip()
        declared = f"{s.turning_point or ''} {s.conflict or ''}".strip()
        if not prose or not declared:
            continue
        p_grams, d_grams = _shingles(prose), _shingles(declared)
        if not p_grams or not d_grams:
            continue
        if not (p_grams & d_grams):
            out.append(
                Finding(
                    code="prose_structure_fidelity",
                    severity=Severity.INFO,
                    message=(
                        f"场景「{s.title or s.id}」的正文与它声明的"
                        f"转折点/冲突零词汇交集 —— 疑似写跑题了"
                    ),
                    suggestion=(
                        "要么让正文真的去写那个转折点，要么改结构声明 —— "
                        "两者不一致时，IR 的下游（渲染、体检）都会读到错误的前提"
                    ),
                    evidence={
                        "scene": s.id,
                        "declared_turning_point": s.turning_point,
                        "declared_conflict": s.conflict,
                        "limitation": "字面重叠：换个措辞写同一个转折会被误报，故只通报不判错",
                    },
                )
            )
    return out


@register("need_revelation_at_climax")
def need_revelation_at_climax(ir: NarrativeIR) -> list[Finding]:
    """高潮有没有兑现角色的 `need`（Truby「自我启示」那一拍）。

    出处：John Truby《The Anatomy of Story》(2007)，中文版《故事写作大师班》
    （豆瓣 8.7）。Truby 序列的最后一拍是 **self-revelation**：
    角色在此刻终于明白自己**真正需要**的是什么，并据此做出**道德决定**。

    与 `desire_need_conflict` 的分工（两个校验器来自同一本书，但不重复）：
      - `desire_need_conflict` 查 **定义**：欲望和需求是不是两个东西
      - 本校验器       查 **兑现**：那个需求有没有在高潮真的被处理

    只查定义不查兑现是不够的：欲望与需求写得再漂亮，
    高潮如果只解决了「想要的」、没碰「需要的」，故事照样塌。

    与 `lie_arc_closure` 的关系：lie 是「假命题」，need 是「真需求」，
    两者都该在高潮被处理，但**处理方向相反**（lie 要被打破，need 要被兑现）。
    故分开报，不合并成一条。

    判据：把 `need` 与**高潮段**（后 30% 场景）的结构字段做字符二元组重叠。
    零重叠 = 需求在高潮从未出现 → 自我启示那一拍缺失。
    取后 30% 而非后 40%（lie 用的口径）是因为自我启示严格发生在高潮，
    比 lie 的「后半程逐渐被触及」更靠后。

    局限：字面重叠，认不出同义改写。
    """
    scenes = ir.ordered_scenes()
    if len(scenes) < 3:
        return []
    climax = scenes[int(len(scenes) * 0.7) :]
    climax_text = " ".join(
        f"{s.turning_point} {s.conflict} {s.value} {s.goal} {s.outcome or ''}"
        for s in climax
    )
    climax_grams = _shingles(climax_text)
    if not climax_grams:
        return []

    out: list[Finding] = []
    for ch in ir.characters.characters.values():
        need = (ch.need or "").strip()
        if not need:
            continue
        grams = _shingles(need)
        if not grams:
            continue
        if not (grams & climax_grams):
            out.append(
                Finding(
                    code="need_revelation_at_climax",
                    severity=Severity.WARN,
                    message=(
                        f"角色「{ch.name}」的需求（{need}）在高潮段从未被触及 —— "
                        "自我启示那一拍缺失"
                    ),
                    suggestion=(
                        "Truby：高潮必须由**需求**驱动，不是由欲望驱动 —— "
                        "让角色在此刻放弃欲望、选择需求（或反过来，死守欲望而失去需求）。"
                        "只解决「想要的」而没碰「需要的」，故事会在最后一刻塌掉"
                    ),
                    evidence={
                        "character": ch.name,
                        "need": ch.need,
                        "climax_scenes": [s.id for s in climax],
                        "limitation": "字面判据：认不出同义改写",
                    },
                )
            )
    return out


@register("lie_arc_closure")
def lie_arc_closure(ir: NarrativeIR) -> list[Finding]:
    """⑦ 高潮是否真的处理了角色的 `lie`。

    出处：Egri《The Art of Dramatic Writing》的「前提必须被论证」+
    四卡机制里的「锚」概念（小传是最高优先级真源，剧情必须兑现它）。

    `lie` 是「角色信以为真的命题」。它与 `flaw` 的区别正是可验证性：
    「傲慢」无法与任何东西比对，「只要我不在乎就不会再受伤」可以。
    因此本校验器可以问一个 `flaw` 问不出的问题：**这个命题在剧中被处理了吗？**

    判据：把 `lie` 与「后半程」（后 40% 场景）的结构字段做字符二元组重叠。
    重叠为零 = 该 lie 在后半程完全没被触及 —— 角色的内在弧线没有闭合。
    只看后半程是因为 lie 通常在中点之后才被正面处理；
    前半程提及只算铺垫，不算兑现。

    局限（写出来，不藏着）：纯字面重叠，认不出「同义改写」。
    作者用完全不同的措辞处理同一个 lie 时本校验器会漏报。
    """
    out: list[Finding] = []
    scenes = ir.ordered_scenes()
    if len(scenes) < 2:
        return out
    late = scenes[int(len(scenes) * 0.6) :]
    late_text = " ".join(
        f"{s.turning_point} {s.conflict} {s.value} {s.goal}" for s in late
    )
    late_grams = _shingles(late_text)

    for ch in ir.characters.characters.values():
        lie = (ch.lie or "").strip()
        if not lie:
            continue
        grams = _shingles(lie)
        if not grams:
            continue
        overlap = len(grams & late_grams)
        if overlap == 0:
            out.append(
                Finding(
                    code="lie_arc_closure",
                    severity=Severity.WARN,
                    message=(
                        f"角色「{ch.name}」的 lie（{lie}）在后半程完全没有被触及 —— "
                        "内在弧线没有闭合"
                    ),
                    suggestion=(
                        "让高潮迫使角色正面面对这个命题：要么放弃它（成长），"
                        "要么死守它（悲剧）。两条都可以，但必须选一条"
                    ),
                    evidence={"character": ch.id, "lie": lie, "late_overlap": 0},
                )
            )
    return out


# ---------------------------------------------------------------------------
# ② ToM
# ---------------------------------------------------------------------------


@register("belief_consistency")
def belief_consistency(ir: NarrativeIR) -> list[Finding]:
    """② 信念标注与客观真值是否自洽。

    出处：认知叙事学的 ToM（theory of mind）模型 —— 角色的行动由其**信念**
    驱动，而非由客观真值驱动。戏剧反讽、误会导致的悲剧、秘密的张力，
    全都建立在「信念 ≠ 真值」之上。

    Keel 原先的 `CharacterState.knows` 只是一个 id 列表，**没有真值可比**，
    因此结构上无法表达「读者知道 X，角色以为 Y」。本校验器用的正是新增的
    真值层 `NarrativeIR.objective_truth`。

    两条判据：
      * `is_erroneous=True` 但值**与真值一致** → 标注错了（WARN）。
        这个错误会污染所有下游的张力派生。
      * `is_erroneous=False` 但值**与真值不一致** → 未标注的错误信念（WARN）。
        更危险：模型以为角色知道真相，其实不知道 —— 于是该有的张力不会被生成。

    真值层为空 = 降级（SKIPPED），不是通过。
    """
    out: list[Finding] = []
    truth = ir.objective_truth
    if not truth:
        return out

    for ch in ir.characters.characters.values():
        bs = ch.belief_state
        if bs is None:
            continue
        for prop, belief in sorted(bs.world_beliefs.items()):
            if prop not in truth:
                continue
            agrees = belief.value == truth[prop]
            if belief.is_erroneous and agrees:
                out.append(
                    Finding(
                        code="belief_consistency",
                        severity=Severity.WARN,
                        message=(
                            f"角色「{ch.name}」的信念「{prop}」被标为错误信念，"
                            f"但它的值与客观真值一致（都是 {belief.value!r}）"
                        ),
                        suggestion="错误信念标注反了 —— 它会污染所有下游张力派生",
                        evidence={
                            "character": ch.id,
                            "proposition": prop,
                            "kind": "mislabeled_erroneous",
                        },
                    )
                )
            elif not belief.is_erroneous and not agrees:
                out.append(
                    Finding(
                        code="belief_consistency",
                        severity=Severity.WARN,
                        message=(
                            f"角色「{ch.name}」相信「{prop}」= {belief.value!r}，"
                            f"但客观真值是 {truth[prop]!r} —— 这是错误信念却未标注"
                        ),
                        suggestion=(
                            "标上 is_erroneous=True。这正是戏剧反讽的原料："
                            "读者知道真相，角色不知道"
                        ),
                        evidence={
                            "character": ch.id,
                            "proposition": prop,
                            "kind": "unmarked_erroneous",
                        },
                    )
                )
    return out


@register("dramatic_irony_available")
def dramatic_irony_available(ir: NarrativeIR) -> list[Finding]:
    """② 可用的戏剧反讽点 —— **报表项，不是门禁；且走 advisory 通道。**

    它**永远输出 INFO，永远不会让作品不通过**，因此按本项目「分类必须可机检」
    的规矩，它被登记在 `REPORTS` 而不是门禁里，不计入「N 个校验器」。

    为什么是报表项而不是门禁：这是 Keel 第一个**向前看**的检查 ——
    它不说「你写错了什么」，它说「你接下来可以写什么」。
    把它当门禁会立刻产生一个荒谬的语义：一个故事「可用反讽点太少」就被判不健康。
    可用的张力点多寡与作品好坏没有单调关系。

    为什么还要进 `ADVISORY`（= 不进健康分）：**只进 REPORTS 是不够的。**
    REPORTS 只保证「不会产出 WARN/ERROR」，但它的 INFO 仍然按
    `score() = 100 - 12×ERROR - 4×WARN - 1×INFO` 每条扣 1 分。
    于是「故事可写的张力越多，健康分越低」—— 一个无法解释的头条指标。
    实测：`TensionSeeder` 一接入基线，本项就会让基线分数凭空下降。

    出处：认知叙事学 ToM 模型。反讽的定义是「读者知道 X，角色以为 Y」，
    需要一个客观真值层 —— 这正是 Keel 原先缺失的那一层。
    """
    out: list[Finding] = []
    if not ir.objective_truth:
        return out

    states = {
        cid: ch.belief_state
        for cid, ch in ir.characters.characters.items()
        if ch.belief_state is not None
    }
    for point in find_dramatic_irony(states, ir.objective_truth):
        out.append(
            Finding(
                code="dramatic_irony_available",
                severity=Severity.INFO,
                message=f"可用反讽点：{point.description}",
                suggestion=point.suggestion,
                evidence={
                    "type": point.type.value,
                    "intensity": point.intensity,
                    "involved": list(point.involved),
                },
            )
        )
    return out


@register("secret_reveal_ordering")
def secret_reveal_ordering(ir: NarrativeIR) -> list[Finding]:
    """② 埋下的秘密有没有被揭示。

    出处：Barthes 阐释符码（谜题的提出与解答）+ 悬念管理的通行做法 ——
    **埋而不揭是烂尾，揭而不埋是突兀**。前者是更常见的失败。

    判据：真值层里的每个命题，若被至少一个角色列为 `known_secrets`，
    就应当在场次结构里被触及（turning_point / conflict / value 的字面重叠）。
    从未被触及 = 埋了没揭 → WARN。

    与 `enigma_resolution` 的分工：那个查的是**显式台账**（`Enigma` 状态机
    posed→delayed→partial→resolved），本校验器查的是**信念层里隐式的秘密**
    —— 一个秘密可以存在而从未被登记成 Enigma，那正是漏网的情形。
    """
    out: list[Finding] = []
    if not ir.objective_truth:
        return out

    holders: dict[str, list[str]] = {}
    for cid, ch in ir.characters.characters.items():
        if ch.belief_state is None:
            continue
        for secret in ch.belief_state.known_secrets:
            holders.setdefault(secret, []).append(cid)
    if not holders:
        return out

    scene_grams = _shingles(
        " ".join(
            f"{s.turning_point} {s.conflict} {s.value}" for s in ir.ordered_scenes()
        )
    )
    resolved_ids = {
        e.id for e in ir.enigmas if e.state is EnigmaState.RESOLVED
    }

    for secret, who in sorted(holders.items()):
        if secret in resolved_ids:
            continue
        if _shingles(secret) & scene_grams:
            continue
        out.append(
            Finding(
                code="secret_reveal_ordering",
                severity=Severity.WARN,
                message=(
                    f"秘密「{secret}」被 {len(who)} 个角色持有，"
                    "但没有任何场景触及它 —— 埋了没揭"
                ),
                suggestion=(
                    "要么安排一场揭示（让它进入 turning_point），"
                    "要么把它从 known_secrets 里去掉 —— 不打算用的秘密不要埋"
                ),
                evidence={"secret": secret, "holders": sorted(who)},
            )
        )
    return out


# ---------------------------------------------------------------------------
# ⑫ 时序边
# ---------------------------------------------------------------------------


@register("relation_temporal")
def relation_temporal(ir: NarrativeIR) -> list[Finding]:
    """⑫ 关系有效期的合法性。

    出处：时序知识图谱的**边有效期**概念 —— 边是有起止的，不是永久事实。
    `CharacterState` 早就有时间维度，`Relation` 没有；本校验器守住新增的
    那两个字段不产生自相矛盾的数据。

    两条判据：
      * `valid_from_day > valid_to_day` → ERROR。区间倒置是硬数据错误，
        任何查询都会得到「从未有效」这种无意义结果。
      * 同一对角色、同一 `kind` 的两条关系**区间重叠** → WARN。
        「第 10 天到第 30 天是朋友」与「第 20 天到第 40 天是朋友」同时成立
        意味着数据冗余或分裂，应当合并成一条。
        **不同 `kind` 的重叠是合法的**（既是朋友又是师徒），故不报。

    时间区间两端都是闭区间。
    """
    out: list[Finding] = []
    rels = ir.bible.relations

    for r in rels:
        if (
            r.valid_from_day is not None
            and r.valid_to_day is not None
            and r.valid_from_day > r.valid_to_day
        ):
            out.append(
                Finding(
                    code="relation_temporal",
                    severity=Severity.ERROR,
                    message=(
                        f"关系 {r.src}→{r.dst}（{r.kind}）的区间倒置："
                        f"{r.valid_from_day} 天开始，{r.valid_to_day} 天结束"
                    ),
                    suggestion="区间倒置会让任何时间查询都得到「从未有效」",
                    evidence={
                        "src": r.src,
                        "dst": r.dst,
                        "kind": r.kind,
                        "from": r.valid_from_day,
                        "to": r.valid_to_day,
                    },
                )
            )

    by_key: dict[tuple[str, str, str], list] = {}
    for r in rels:
        key = (r.src, r.dst, r.kind)
        by_key.setdefault(key, []).append(r)

    for (src, dst, kind), group in sorted(by_key.items()):
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                lo_a = a.valid_from_day if a.valid_from_day is not None else 0
                hi_a = a.valid_to_day if a.valid_to_day is not None else 10**9
                lo_b = b.valid_from_day if b.valid_from_day is not None else 0
                hi_b = b.valid_to_day if b.valid_to_day is not None else 10**9
                if max(lo_a, lo_b) <= min(hi_a, hi_b):
                    out.append(
                        Finding(
                            code="relation_temporal",
                            severity=Severity.WARN,
                            message=(
                                f"{src}→{dst} 的「{kind}」有两条区间重叠的关系，"
                                "应当合并为一条"
                            ),
                            suggestion=(
                                "同一对角色同一类型的关系在时间上重叠 = 数据分裂。"
                                "不同 kind 的重叠是合法的（既是朋友又是师徒），故不报"
                            ),
                            evidence={"src": src, "dst": dst, "kind": kind},
                        )
                    )
    return out


# ---------------------------------------------------------------------------
# 读数项（ADVISORY_READOUT）：测量，不是缺陷
# ---------------------------------------------------------------------------


@register("mice_thread_closure")
def mice_thread_closure(ir: NarrativeIR) -> list[Finding]:
    """MICE 四类线程的开合视图 —— 「这个故事开了什么线、收了没有」。

    出处：Orson Scott Card, *How to Write Science Fiction and Fantasy* /
    *Characters and Viewpoint* 中的 **MICE Quotient**：
    Milieu（环境）/ Idea（疑问）/ Character（角色）/ Event（事件）。
    每种线程各有自己的**开场与收场**，故事结束的时机由主导线程决定。

    **为什么它是读数项而不是门禁项**（重要，别改成门禁）：
    「未闭合」这件事**已经有专门的门禁在报** ——
      - Event 线程 → `enigma_resolution`（未解 / 遗弃 → ERROR）
      - Idea 线程  → `secret_reveal_ordering`（埋而不揭 → WARN）
      - Character 线程 → `lie_arc_closure` + `need_revelation_at_climax`
    再造一个门禁去报同一批问题，只会**让同一件事被罚两次分**，
    而且把「哪一类线没关」这个**类型判断**混进「有缺陷」的是非判断里。

    本项贡献的是门禁给不了的东西：**把四条线放在一个框架里并排看**。
    作者真正需要的判断是「我开的是 Event 故事，是不是在用 Character 的收法收尾」——
    这是**类型配不配**的问题，不是「有没有错」。

    判据（四类线程的开启/闭合信号，全部只用现有字段）：
      - Event     开：有谜题台账            合：全部 resolved / abandoned
      - Idea      开：有客观真值且有人知情  合：这些秘密在场次结构里被触及
      - Character 开：角色有 need           合：need 在高潮段被触及
      - Milieu    开：中途出现了首尾都没有的地点  合：结局回到起点或停在新地点
        （地点数据缺失时这一类**不可评估**，会说出来而不跳过）
    """
    scenes = ir.ordered_scenes()
    climax = scenes[int(len(scenes) * 0.7) :] if len(scenes) >= 3 else scenes
    climax_grams = _shingles(
        " ".join(
            f"{s.turning_point} {s.conflict} {s.value} {s.goal} {s.outcome or ''}"
            for s in climax
        )
    )

    lines: list[str] = []
    opened: list[str] = []
    closed: list[str] = []

    # -- Event --
    if ir.enigmas:
        unclosed = [
            e for e in ir.enigmas
            if e.state not in (EnigmaState.RESOLVED, EnigmaState.ABANDONED)
        ]
        opened.append("Event")
        lines.append(
            f"Event：{len(ir.enigmas)} 条谜题，"
            + ("全部回收" if not unclosed else f"{len(unclosed)} 条未回收")
        )
        if not unclosed:
            closed.append("Event")

    # -- Idea --
    truth = ir.objective_truth or {}
    if truth:
        buried = {
            p
            for c in ir.characters.characters.values()
            if c.belief_state is not None
            for p in c.belief_state.known_secrets
        }
        struct_grams = _shingles(
            " ".join(f"{s.turning_point} {s.conflict} {s.value}" for s in scenes)
        )
        revealed = {p for p in buried if _shingles(p) & struct_grams}
        opened.append("Idea")
        if buried and revealed == buried:
            closed.append("Idea")
        lines.append(
            f"Idea：{len(truth)} 条真值，埋 {len(buried)} 揭 {len(revealed)}"
        )

    # -- Character --
    needs = [c for c in ir.characters.characters.values() if (c.need or "").strip()]
    if needs:
        met = [
            c for c in needs
            if _shingles(c.need or "") & climax_grams
        ]
        opened.append("Character")
        if len(met) == len(needs):
            closed.append("Character")
        lines.append(
            f"Character：{len(needs)} 个角色有需求，{len(met)} 个在高潮兑现"
        )

    # -- Milieu --
    locs = [(s.location or "").strip() for s in scenes]
    if any(locs):
        first, last = locs[0], locs[-1]
        mid_new = {l for l in locs[1:-1] if l and l not in (first, last)}
        opened.append("Milieu")
        if mid_new:
            lines.append(
                f"Milieu：进入 {len(mid_new)} 个新地点，"
                + ("结局回到起点" if last == first else "结局停留在新地点")
            )
            closed.append("Milieu")
        else:
            lines.append("Milieu：场景地点未发生变化（首尾同址）")
            closed.append("Milieu")
    else:
        lines.append("Milieu：无地点数据 —— 这一类**不可评估**")

    closed = [c for c in closed if c]
    opened_set = [o for o in opened if o]
    gap = len(opened_set) - len(closed)
    return [
        Finding(
            code="mice_thread_closure",
            severity=Severity.INFO,
            message=(
                f"MICE 线程：开启 {len(opened_set)} 类"
                f"（{'/'.join(opened_set)}），闭合 {len(closed)} 类"
                + (f" —— {gap} 类未闭合" if gap > 0 else " —— 全部闭合")
            ),
            suggestion=(
                "主导线程决定故事该在哪里结束：Event 故事止于秩序恢复，"
                "Idea 故事止于答案揭晓，Character 故事止于角色找到位置，"
                "Milieu 故事止于离开或适应新环境。"
                "收尾方式与主导线程错配 = 读者感到「没写完」"
            ),
            evidence={
                "opened": opened_set,
                "closed": closed,
                "breakdown": lines,
                "limitation": "结构签名推断，非作者自述的主导线程；未闭合已由各专门门禁另行扣分",
            },
        )
    ]


@register("narrative_arc_shape")
def narrative_arc_shape(ir: NarrativeIR) -> list[Finding]:
    """故事形状的**两个可测量维度**：建置占比与推进斜率。

    出处（两篇实证，都不是"大师经验谈"，是有数据的）：
      - Boyd, Blackburn & Pennebaker (2020), *The narrative arc*（187 次引用）：
        用情感分析证明叙事存在**系统性的弧线**，且弧线形状取决于
        **staging**（建置占多少）而不是题材。
      - Toubia, Berger & Eliashberg (2021, PNAS)（78 次引用）：
        用 **progression**（情感推进）与 **change**（波动）两个维度
        量化故事形状，并证明这两个维度对受众反应有解释力。

    **为什么是读数项，且刻意不做判断**：
    Toubia 那篇的标题容易读成「故事形状**预测**成功」。
    但本项目的铁律是**只做结构性排除，不做成功预测** ——
    我们没有真实留存数据，也拒绝对标他们的回归系数。
    所以这里**只报两个数，不下结论**：
      - staging     第一个情感极值的位置占比（建置有多长）
      - progression 情感的线性趋势斜率（往哪个方向走）
    这两个数让作者看见自己的故事形状，判断留给作者。
    """
    scenes = ir.ordered_scenes()
    if len(scenes) < 3:
        return []
    ys = [s.emotion for s in scenes if s.emotion is not None]
    if len(ys) < 3:
        return []
    n = len(ys)

    # staging：第一个极值（谷或峰，取先出现的）落在全篇的哪个位置
    i_min, i_max = ys.index(min(ys)), ys.index(max(ys))
    turning = min(i_min, i_max)
    staging = turning / (n - 1)

    # progression：等距采样的线性回归斜率（闭式解，零依赖）
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs) or 1.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom

    shape = "先跌后起" if i_min < i_max else "先起后跌"
    return [
        Finding(
            code="narrative_arc_shape",
            severity=Severity.INFO,
            message=(
                f"故事形状：建置占 {staging:.0%}"
                f"（第 {turning + 1}/{n} 场转折），"
                f"推进斜率 {slope:+.2f}／场，{shape}"
            ),
            suggestion=(
                "两个数都是**测量**，不是评分。建置过长会让中段乏力，"
                "推进接近零意味着全场情绪没走 —— 但怎么取舍是作者的判断"
            ),
            evidence={
                "staging": round(staging, 3),
                "progression": round(slope, 4),
                "turning_index": turning,
                "shape": shape,
                "limitation": "只报测量值；不套用 Toubia 的回归系数做成功预测（无校准数据）",
            },
        )
    ]
