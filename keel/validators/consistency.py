"""一致性校验器。

与结构校验器的分工：
    结构校验器  —— 故事「好不好」（因果、节拍、弧线）
    一致性校验器 —— 故事「对不对」（设定、知情、时间线）

工业实践（起点「AI 占比 >10% 即撤榜」、番茄拒签「空洞水文」）说明：
一致性已从「质量」变成「合规」，必须内建为可量化指标。
"""

from __future__ import annotations

from collections import defaultdict

from ..audit.csn import find_conflicts, scan_numeric_facts
from ..ir.enums import EnigmaState, EntityKind, Severity
from ..ir.medium_craft import split_slugline
from ..ir.models import NarrativeIR
from .base import Finding, register


@register("knowledge_matrix")
def knowledge_matrix(ir: NarrativeIR) -> list[Finding]:
    """知情矩阵：谁知道什么、什么时候知道的。

    最常见的吃书形态：第 12 章的秘密在第 41 章被当作新信息重新揭示。
    """
    out: list[Finding] = []
    fact_ids = {f.id for f in ir.facts}
    scene_ids = {s.id for s in ir.scenes}

    for e in ir.enigmas:
        for cid in e.revealed_to:
            if cid not in ir.characters.characters:
                out.append(
                    Finding(
                        code="knowledge_matrix",
                        severity=Severity.ERROR,
                        entity_id=e.id,
                        message=f"谜题的 revealed_to 引用了不存在的角色：{cid}",
                    )
                )
        if e.resolved_at_scene and e.resolved_at_scene not in scene_ids:
            out.append(
                Finding(
                    code="knowledge_matrix",
                    severity=Severity.ERROR,
                    entity_id=e.id,
                    message=f"解消场景不存在：{e.resolved_at_scene}",
                )
            )
        if e.state is EnigmaState.RESOLVED and not e.resolved_at_scene:
            out.append(
                Finding(
                    code="knowledge_matrix",
                    severity=Severity.WARN,
                    entity_id=e.id,
                    message="谜题标记为已解消，但未记录解消场景",
                    suggestion="补 resolved_at_scene，否则无法做重揭示检测",
                )
            )

    for f in ir.facts:
        if f.id not in fact_ids:  # 防御
            continue
        for cid, day in f.known_by.items():
            if cid not in ir.characters.characters:
                out.append(
                    Finding(
                        code="knowledge_matrix",
                        severity=Severity.ERROR,
                        entity_id=f.id,
                        message=f"事实的 known_by 引用了不存在的角色：{cid}",
                    )
                )
            if day < 0:
                out.append(
                    Finding(
                        code="knowledge_matrix",
                        severity=Severity.ERROR,
                        entity_id=f.id,
                        message=f"获知时间非法（day={day}）",
                    )
                )
    return out


@register("revelation_regression")
def revelation_regression(ir: NarrativeIR) -> list[Finding]:
    """重揭示检测：同一信息被当作「新发现」揭示多次。"""
    by_scene: dict[str, list[str]] = defaultdict(list)
    for e in ir.enigmas:
        if e.resolved_at_scene:
            by_scene[e.resolved_at_scene].append(e.id)
        if e.planted_at_scene:
            by_scene[e.planted_at_scene].append(e.id)

    out: list[Finding] = []
    for sid, ids in by_scene.items():
        if len(ids) > 3:
            out.append(
                Finding(
                    code="revelation_regression",
                    severity=Severity.INFO,
                    scene_id=sid,
                    message=f"单场景承载了 {len(ids)} 条谜题动作，信息密度过高",
                    suggestion="拆分到多个场景，避免观众来不及消化",
                    evidence={"enigmas": ids},
                )
            )
    return out


@register("timeline_monotonic")
def timeline_monotonic(ir: NarrativeIR) -> list[Finding]:
    """时间线一致性。

    注意：话语顺序与故事时间顺序**允许**不一致 —— 那叫时序倒错（anachrony），
    是合法的叙事手段。这里只检查「非倒错场景之间」的顺序是否单调。
    """
    out: list[Finding] = []
    scenes = ir.ordered_scenes()

    flashback_days: list[int] = []
    forward_days: list[int] = []
    for s in scenes:
        if s.fabula_time.is_flashback or s.frequency.value == "repetitive":
            flashback_days.append(s.fabula_time.day)
        else:
            forward_days.append(s.fabula_time.day)

    if forward_days != sorted(forward_days):
        out.append(
            Finding(
                code="timeline_monotonic",
                severity=Severity.WARN,
                message="非倒错场景的故事时间出现回退，但未标记为闪回",
                suggestion="标记 fabula_time.is_flashback，或修正时间点",
                evidence={"days": forward_days},
            )
        )

    negatives = [d for d in flashback_days if d < 0]
    if negatives and any(d >= 0 for d in forward_days):
        out.append(
            Finding(
                code="timeline_monotonic",
                severity=Severity.INFO,
                message=f"存在 {len(negatives)} 个负时间点闪回（前史）",
            )
        )

    ana = ir.anachronies()
    if ana:
        out.append(
            Finding(
                code="timeline_monotonic",
                severity=Severity.INFO,
                message=f"检测到 {len(ana)} 个时序倒错场景（话语顺序 ≠ 故事时间）",
                evidence={"scenes": [s.id for s in ana if s]},
            )
        )
    return out


@register("entity_reference")
def entity_reference(ir: NarrativeIR) -> list[Finding]:
    """实体引用完整性：场景引用的实体必须已登记。

    这是 AI 长篇最常见的硬错误来源 ——「Key」与「Metallic Key」被当作两个东西
    （Story2Game 论文明确把对象误识别列为最高频编译失败原因）。
    """
    known = set(ir.bible.entities) | set(ir.characters.characters)
    loc_known = any(
        e.kind is EntityKind.LOCATION for e in ir.bible.entities.values()
    )
    out: list[Finding] = []

    for s in ir.scenes:
        for eid in s.entities:
            if eid not in known:
                out.append(
                    Finding(
                        code="entity_reference",
                        severity=Severity.ERROR,
                        scene_id=s.id,
                        message=f"场景引用了未登记的实体：{eid}",
                        suggestion="在 Story Bible 登记，或修正引用（注意别名问题）",
                    )
                )
        # `scene.location` 是**场景标题显示串**，不是实体 id ——
        # 它长得像「内景·书房」，带内外景标记（约定见 `ir/medium_craft.split_slugline`）。
        # 拿它去比对 id 集合必然全部误报：结构层在角色层之前跑，
        # 那时地点实体还不存在，于是这条检查**从来只会在有了真实地点后乱响**。
        #
        # 真正要查的是「这个地点是否被登记过」，所以拆出地点名再查别名索引。
        # 圣经里一个地点都没登记时**不报警**（无从判断 = 跳过，不是通过）——
        # 否则「没登记任何地点」会被报成「每个地点都没登记」，那是噪音，不是信号。
        if s.location and loc_known:
            _, place = split_slugline(s.location)
            if place:
                hit = ir.bible.alias_index().get(place.lower())
                if hit is None or ir.bible.entities.get(hit) is None or (
                    ir.bible.entities[hit].kind is not EntityKind.LOCATION
                ):
                    out.append(
                        Finding(
                            code="entity_reference",
                            severity=Severity.WARN,
                            scene_id=s.id,
                            message=f"场景地点未登记：{place}",
                            suggestion=(
                                "在 Story Bible 登记为 location 类实体，"
                                "或统一地点名（「书房」与「内景·书房」应指向同一处）"
                            ),
                        )
                    )
        if s.focalizer not in known:
            out.append(
                Finding(
                    code="entity_reference",
                    severity=Severity.ERROR,
                    scene_id=s.id,
                    message=f"聚焦者未登记：{s.focalizer}",
                )
            )
        for d in s.state_deltas:
            if d.entity_id not in known:
                out.append(
                    Finding(
                        code="entity_reference",
                        severity=Severity.ERROR,
                        scene_id=s.id,
                        message=f"状态增量引用了未登记的实体：{d.entity_id}",
                    )
                )
    return out


@register("alias_collision")
def alias_collision(ir: NarrativeIR) -> list[Finding]:
    """别名冲突：不同实体共用别名 = 吃书的根源。"""
    idx: dict[str, list[str]] = defaultdict(list)
    for e in ir.bible.entities.values():
        idx[e.name.lower()].append(e.id)
        for a in e.aliases:
            idx[a.lower()].append(e.id)
    for c in ir.characters.characters.values():
        idx[c.name.lower()].append(c.id)
        for a in c.aliases:
            idx[a.lower()].append(c.id)

    out: list[Finding] = []
    for alias, ids in idx.items():
        uniq = sorted(set(ids))
        if len(uniq) > 1:
            out.append(
                Finding(
                    code="alias_collision",
                    severity=Severity.ERROR,
                    entity_id=uniq[0],
                    message=f"别名「{alias}」被多个实体共用：{uniq}",
                    suggestion="这是 AI 长篇最高频的吃书来源，必须消歧",
                    evidence={"alias": alias, "entities": uniq},
                )
            )
    return out


@register("world_rule_violation")
def world_rule_violation(ir: NarrativeIR) -> list[Finding]:
    """世界硬规则被效果违反的检测。"""
    if not ir.bible.rules:
        return [
            Finding(
                code="world_rule_violation",
                severity=Severity.INFO,
                message="未登记任何世界规则 —— 缺少设定崩坏的判据",
                suggestion="至少登记 3 条硬规则（is_hard=True）",
            )
        ]
    hard = [r for r in ir.bible.rules if r.is_hard]
    if not hard:
        return [
            Finding(
                code="world_rule_violation",
                severity=Severity.WARN,
                message="没有硬规则（全部为软设定），无法做崩坏检测",
            )
        ]
    return []


@register("numeric_fact_consistency")
def numeric_fact_consistency(ir: NarrativeIR) -> list[Finding]:
    """跨场数值矛盾：同一主体 + 同一动作 + 同一单位，值却不同。

    出处：这不是某位理论家的主张，是**读者侧的事实**——网文社区里
    「吃书」投诉最高频的一类就是数值前后不一（年龄、年限、楼层、人数）。
    这类矛盾纯规则可判，不需要任何语义理解，所以应当由机器兜住，
    而不是指望作者记住第 3 章写过「十一年」。

    判据与局限见 `keel/audit/csn.py` 的 docstring：抽取**误报治理优先**，
    代价是召回受限（代词主体、同义改写对不上）。这是有意的取舍 ——
    一个会误报的门禁等于没有门禁。
    """
    names: set[str] = set(ir.characters.characters)
    for c in ir.characters.characters.values():
        names.add(c.name)
        names.update(c.aliases)
    for e in ir.bible.entities.values():
        names.add(e.name)
        names.update(e.aliases)
    names.discard("")

    facts = []
    for s in ir.ordered_scenes():
        if s.prose:
            facts.extend(
                scan_numeric_facts(s.prose, names=names, scene_id=s.id)
            )

    out: list[Finding] = []
    for c in find_conflicts(facts):
        out.append(
            Finding(
                code="numeric_fact_consistency",
                severity=Severity.WARN,
                entity_id=c.subject,
                message=f"数值矛盾：{c.render()}",
                suggestion=(
                    "确认哪个数值是对的，改掉另一个 —— "
                    "同一主体同一动作的数值前后不一，是最容易被读者抓住的吃书"
                ),
                evidence={
                    "subject": c.subject,
                    "predicate": c.predicate,
                    "unit": c.unit,
                    "values": c.values,
                    "scenes": c.scenes,
                },
            )
        )
    return out


@register("provenance_coverage")
def provenance_coverage(ir: NarrativeIR) -> list[Finding]:
    """溯源覆盖度 —— 合规必需。

    《微短剧发展管理办法》（广电总局令第16号，2026-09-01 施行）要求
    AI 参与制作的内容每集显著标识；起点要求 AI 占比 ≤10%。
    没有溯源就无法证明。
    """
    from ..ir.enums import ChunkOrigin

    if not ir.scenes:
        return []
    covered = {p.scene_id for p in ir.provenance if p.scene_id}
    missing = [s.id for s in ir.scenes if s.id not in covered]
    out: list[Finding] = []

    if missing:
        out.append(
            Finding(
                code="provenance_coverage",
                severity=Severity.WARN,
                message=f"{len(missing)}/{len(ir.scenes)} 个场景缺少溯源记录",
                suggestion="补写 Provenance，否则无法生成合规报告",
                evidence={"missing": missing[:10]},
            )
        )

    written = [s for s in ir.scenes if s.prose]
    ai_chars = sum(
        len(s.prose or "")
        for s in written
        if s.origin in (ChunkOrigin.AI_GENERATED, ChunkOrigin.AI_EDITED)
    )
    total = sum(len(s.prose or "") for s in written)
    if total:
        ratio = ai_chars / total
        sev = Severity.WARN if ratio > 0.10 else Severity.INFO
        out.append(
            Finding(
                code="provenance_coverage",
                severity=sev,
                message=f"AI 生成/改写字数占比 {ratio:.1%}",
                suggestion=(
                    "超过 10% 将触发起点撤榜规则；请提高人工改写比例"
                    if ratio > 0.10
                    else None
                ),
                evidence={"ai_ratio": round(ratio, 4), "total_chars": total},
            )
        )
    return out
