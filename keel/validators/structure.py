"""结构校验器。

每条都对应一个真实的方法论来源，不是凭空发明的启发式。

    value_charge_flip      McKee《故事》：场景结束时价值状态必须改变
    state_delta            Todorov：平衡→失衡→新平衡，零增量即无场景
    commitment_satisfied   Riedl & Young IPOCL：作者承诺层硬约束
    enigma_resolution      Barthes《S/Z》阐释符码：悬空未解 = 烂尾
    mirror_bookends        Snyder：终场画面是开场画面的镜像
    emotion_curve_match    Reagan et al. 2016：实证六种情感弧线
    li_yu_main_brain       李渔《闲情偶寄》：立主脑
    li_yu_reduce_threads   李渔：减头绪
    mao_repeat_variation   毛宗岗《读三国志法》：犯而不犯
    actant_collision       Greimas 行动元：一人占两位 = 反转信号
    focalizer_boundary     Genette：内聚焦不得越界
    causal_chain_integrity POCL：前置条件必须被满足
    hook_cadence           短剧行业惯例：集末必须有钩子
    paywall_gate_present   短剧：付费边界是一等结构节点
"""

from __future__ import annotations

from collections import Counter

from ..ir.arcs import (
    ARC_ANCHORS,
    declared_extremum,
    interior_extremum,
    interpolate,
    third_of,
)
from ..ir.devices import check_saturation, infer_patterns
from ..ir.enums import (
    ActantRole,
    ArcShape,
    EnigmaState,
    Focalization,
    Medium,
    SceneOutcome,
    Severity,
)
from ..ir.models import NarrativeIR
from ..ir.templates import get_template
from .base import Finding, register


def _progress(ir: NarrativeIR) -> dict[str, float]:
    """每个场景在整体中的相对进度（按话语顺序）。"""
    scenes = ir.ordered_scenes()
    n = len(scenes)
    if n == 0:
        return {}
    if n == 1:
        return {scenes[0].id: 0.5}
    return {s.id: i / (n - 1) for i, s in enumerate(scenes)}


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


# ---------------------------------------------------------------------------


@register("value_charge_flip")
def value_charge_flip(ir: NarrativeIR) -> list[Finding]:
    """McKee：每个场景都是一次价值转折。"""
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.value_flips:
            out.append(
                Finding(
                    code="value_charge_flip",
                    severity=Severity.ERROR,
                    scene_id=s.id,
                    message=f"场景未产生价值转折（「{s.value}」全程 {s.value_charge_start}）",
                    suggestion="让价值极性反转（+→- 或 -→+），或把本场景并入相邻场景",
                    evidence={"value": s.value},
                )
            )
    return out


@register("state_delta")
def state_delta(ir: NarrativeIR) -> list[Finding]:
    """Todorov：场景必须移动至少一个被追踪的变量。"""
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.state_deltas:
            out.append(
                Finding(
                    code="state_delta",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message="场景没有任何状态增量（零增量场景）",
                    suggestion="补一个 StateDelta，或标记本场景为「铺垫」并接受它不推进",
                )
            )
    return out


@register("commitment_satisfied")
def commitment_satisfied(ir: NarrativeIR) -> list[Finding]:
    """L3 作者承诺层：承诺必须**有落点**。Riedl & Young IPOCL 硬约束。

    ── 这个校验器能判什么、不能判什么（必读）──────────────────────

    **能判**：承诺的 `must_hold_at` 是否指向真实存在的场景。
    这是纯结构事实，二值、无歧义，且只有作者能修。

    **不能判**：承诺的**主题内容**是否真的在正文里兑现了。

    这里曾经用「statement 关键词是否出现在目标场景文本中」当代理，
    实测证明该代理在中文上**恒假**：它按「连续 ASCII 字母数字 / CJK
    汉字」切 token，而中文没有词边界，于是一整句被切成**一个** token
    —— `「信任不是一种判断，而是一种交付。」` 切出的是
    `["信任不是一种判断", "而是一种交付"]` 两个 6~8 字整句，
    而正文永远不可能逐字复现整句。

    实测（`scripts/pipeline_demo.py`，2026-09-19）：7 条承诺 7 条误报
    「未兑现」，健康分从 92 塌到 21，错误 0 变成 6 —— 一个**对着正常
    故事开火的假门禁**，比原先那个恒真的假门禁更糟。

    退一步改用字符二元组（`drift._shingles` 的既有做法）同样不行：
    实测重叠率只有 0.05~0.10，没有任何阈值能把「兑现了」与「没兑现」
    分开。原因不是分词不好，而是**承诺措辞与场景措辞本来就是两套
    独立生成的词表**（承诺是抽象主题句，场景是具体动作句）。

    结论：**主题兑现不是可机判的**，故本校验器**不产出**这类判定 ——
    铁律 24：证据不足时不判定，而不是判定为通过，更不是判定为失败。
    L3 真正的可测执行力在 `drift.drift_guard`（用字符 shingle 测
    「尾窗还在不在论点上」，那是可测的结构信号）；本校验器只负责
    「承诺有没有落点」这个更弱、但**为真**的判据。
    """
    out: list[Finding] = []
    scene_map = {s.id: s for s in ir.scenes}
    for c in ir.commitment.commitments:
        missing = [sid for sid in c.must_hold_at if sid not in scene_map]
        if missing:
            out.append(
                Finding(
                    code="commitment_satisfied",
                    severity=Severity.ERROR,
                    entity_id=c.id,
                    message=f"承诺指向的场景不存在：{missing}",
                    suggestion="补齐场景，或修正承诺的 must_hold_at",
                    evidence={"must_hold_at": c.must_hold_at},
                )
            )
    if not ir.commitment.commitments:
        out.append(
            Finding(
                code="commitment_satisfied",
                severity=Severity.WARN,
                message="承诺层为空 —— 系统无法防止输出漂离论点",
                suggestion="至少加入一条 theme 承诺和一条 ending 承诺",
            )
        )
    return out


@register("enigma_resolution")
def enigma_resolution(ir: NarrativeIR) -> list[Finding]:
    """Barthes 阐释符码：谜题台账。悬空未解是烂尾信号。"""
    out: list[Finding] = []
    for e in ir.enigmas:
        if e.state is EnigmaState.ABANDONED:
            out.append(
                Finding(
                    code="enigma_resolution",
                    severity=Severity.ERROR,
                    entity_id=e.id,
                    message=f"谜题被遗弃（烂尾信号）：{e.question}",
                    suggestion="要么回收，要么从台账中删除",
                )
            )
        elif e.state in (EnigmaState.POSED, EnigmaState.DELAYED, EnigmaState.PARTIAL):
            out.append(
                Finding(
                    code="enigma_resolution",
                    severity=Severity.WARN,
                    entity_id=e.id,
                    message=f"谜题未回收（{e.state.value}）：{e.question}",
                    suggestion=(
                        f"已规划在 {e.planned_resolution_scene} 回收"
                        if e.planned_resolution_scene
                        else "尚未规划回收点 —— 埋设即应登记回收位置"
                    ),
                )
            )
        if e.planned_resolution_scene and e.planned_resolution_scene not in {
            s.id for s in ir.scenes
        }:
            out.append(
                Finding(
                    code="enigma_resolution",
                    severity=Severity.ERROR,
                    entity_id=e.id,
                    message=f"规划的回收场景不存在：{e.planned_resolution_scene}",
                )
            )
    if ir.enigmas and not any(e.is_foreshadow for e in ir.enigmas):
        out.append(
            Finding(
                code="enigma_resolution",
                severity=Severity.INFO,
                message="台账中没有任何伏笔类条目",
                suggestion="长篇至少应有 3-5 条贯穿性伏笔（草蛇灰线）",
            )
        )
    return out


@register("mirror_bookends")
def mirror_bookends(ir: NarrativeIR) -> list[Finding]:
    """Snyder：终场画面是开场画面的镜像。"""
    scenes = ir.ordered_scenes()
    if len(scenes) < 2:
        return []
    first, last = scenes[0], scenes[-1]
    if first.value == last.value and first.value_charge_start == last.value_charge_end:
        return [
            Finding(
                code="mirror_bookends",
                severity=Severity.INFO,
                scene_id=last.id,
                message=(
                    f"首尾状态完全相同（「{first.value}」"
                    f"{first.value_charge_start} → {last.value_charge_end}），"
                    f"净变化为零"
                ),
                # 原文案写的是「终场画面应与开场画面互为镜像」，与判据自相矛盾 ——
                # 判据抓的正是「首尾同形」。Snyder 的镜像指画面相同而人物已不同；
                # 这里抓到的是「连状态都没变」，是另一回事。
                suggestion=(
                    "确认这是刻意的回到原点（如悲剧循环），还是结尾缺少净变化 —— "
                    "若是后者，让终场的价值状态带上开场所没有的东西"
                ),
            )
        ]
    return []


_ARC_ANCHORS = ARC_ANCHORS  # 定义已上移到 keel/ir/arcs.py，此处保留别名


@register("emotion_curve_match")
def emotion_curve_match(ir: NarrativeIR) -> list[Finding]:
    """情感曲线是否匹配声明的弧线形状（Reagan et al. 2016）。

    **两条独立判据**，因为相关系数单独用是不够的：

      1. 相关度 `r`：曲线整体走向是否与声明弧线同向
      2. 转折点位置：声明弧线的内部极值（谷/峰）是否真的出现在文本里

    第 2 条是 fixture 库逼出来的。反例：一条**单调上升**的情感曲线，
    与 `man_in_a_hole`（先跌后起）声明弧线的 Pearson r 高达 **0.49**，
    因为「从谷底回升」占多数采样点，足以把相关系数拉正。
    只查 r > 0.3 会判「匹配度良好」——**完全没有谷的故事通过了谷型弧线**。
    只报一个 r 是自欺：它测的是「趋势同向」，不是「形状对」。
    """
    prog = _progress(ir)
    scenes = ir.ordered_scenes()
    if len(scenes) < 3:
        return []
    arc = ir.commitment.arc_shape
    anchors = ARC_ANCHORS[arc]
    xs = [s.emotion for s in scenes]
    positions = [prog[s.id] for s in scenes]
    ys = [interpolate(anchors, p) for p in positions]
    r = _pearson(xs, ys)

    out: list[Finding] = []
    if r < 0.3:
        out.append(
            Finding(
                code="emotion_curve_match",
                severity=Severity.WARN,
                message=(
                    f"情感曲线与声明的弧线「{arc.value}」相关性偏低（r={r:.2f}）"
                ),
                suggestion="调整各场景 emotion 值，或改声明更贴合的弧线形状",
                evidence={"pearson_r": round(r, 3)},
            )
        )

    decl = declared_extremum(arc)
    obs = interior_extremum(xs, positions)
    if decl is not None:
        d_kind, d_pos = decl
        if obs is None:
            out.append(
                Finding(
                    code="emotion_curve_match",
                    severity=Severity.WARN,
                    message=(
                        f"声明的弧线「{arc.value}」在 {d_pos:.0%} 处有一个"
                        f"{'谷底' if d_kind == 'min' else '峰值'}，"
                        f"但文本的情感曲线是单调的 —— 转折点没有出现"
                    ),
                    suggestion=(
                        f"让 emotion 在 {max(0.0, d_pos - 0.15):.0%}-"
                        f"{min(1.0, d_pos + 0.15):.0%} 处达到"
                        f"{'最低' if d_kind == 'min' else '最高'}，"
                        f"或改声明单调弧线（rags_to_riches / tragedy）"
                    ),
                    evidence={"declared": {"kind": d_kind, "at": round(d_pos, 3)}},
                )
            )
        elif obs[0] != d_kind or third_of(obs[1]) != third_of(d_pos):
            out.append(
                Finding(
                    code="emotion_curve_match",
                    severity=Severity.WARN,
                    message=(
                        f"转折点错位：声明弧线「{arc.value}」的"
                        f"{'谷底' if d_kind == 'min' else '峰值'}在 {d_pos:.0%} 处，"
                        f"文本的{'谷底' if obs[0] == 'min' else '峰值'}却落在 "
                        f"{obs[1]:.0%} 处"
                    ),
                    suggestion="把情感转折挪到声明弧线规定的位置",
                    evidence={
                        "declared": {"kind": d_kind, "at": round(d_pos, 3)},
                        "observed": {"kind": obs[0], "at": round(obs[1], 3)},
                    },
                )
            )

    if out:
        return out
    return [
        Finding(
            code="emotion_curve_match",
            severity=Severity.INFO,
            message=f"情感曲线匹配度良好（r={r:.2f}，转折点位置一致）",
        )
    ]


@register("li_yu_main_brain")
def li_yu_main_brain(ir: NarrativeIR) -> list[Finding]:
    """李渔「立主脑」：一个统领性前提，所有场次必须服务它。

    可检查的解释：任何场景都应被至少一条作者承诺或一个情节事件引用，
    否则它就是「游离场次」。
    """
    referenced = set()
    for c in ir.commitment.commitments:
        referenced.update(c.must_hold_at)
    for ev in ir.plot.events.values():
        if ev.scene_id:
            referenced.add(ev.scene_id)

    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if s.id not in referenced:
            out.append(
                Finding(
                    code="li_yu_main_brain",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message="游离场次：既未承载任何承诺，也未对应任何情节事件",
                    suggestion="删除，或为它补一条承诺/事件以证明它服务主脑",
                )
            )
    return out


@register("li_yu_reduce_threads")
def li_yu_reduce_threads(ir: NarrativeIR) -> list[Finding]:
    """李渔「减头绪」：并发支线上限。工业经验也是 ≤3。

    **窗口必须 ≥ 4，否则这条校验器在数学上不可能触发。**

    原实现是 `window = max(3, len(scenes) // 3)`。一个宽度为 3 的窗口里
    最多只能出现 3 个不同的取值，而判据是 `len(threads) > 3` ——
    恒为假。后果：所有场景数 < 12 的故事，这条校验器**永远返回「没问题」**，
    而它实际上一次都没有检查过。这是「静默通过」最纯粹的形式：
    不是判据太松，是判据根本不可满足。

    （同类问题在 fixture 库里被抓出来：注入「窗口内 4 条并发支线」的
    反例时，校验器毫无反应。）
    """
    scenes = ir.ordered_scenes()
    if len(scenes) < 4:
        return []
    window = min(len(scenes), max(4, len(scenes) // 3))
    out: list[Finding] = []
    for i in range(len(scenes) - window + 1):
        chunk = scenes[i : i + window]
        threads = {s.value for s in chunk}
        if len(threads) > 3:
            out.append(
                Finding(
                    code="li_yu_reduce_threads",
                    severity=Severity.WARN,
                    scene_id=chunk[0].id,
                    message=f"窗口内并发支线过多（{len(threads)} 条）：{sorted(threads)}",
                    suggestion="收束支线，完成一条再开新的（并发 ≤3）",
                    evidence={"threads": sorted(threads), "window": window},
                )
            )
    return out


def _tokens(text: str) -> set[str]:
    """极简中英混合分词：中文按 2-gram，英文按词。"""
    text = text.strip().lower()
    out: set[str] = set()
    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    out.update("".join(pair) for pair in zip(cjk, cjk[1:]))
    out.update(w for w in "".join(
        ch if ch.isalnum() else " " for ch in text
    ).split() if len(w) > 1)
    return out


@register("mao_repeat_variation")
def mao_repeat_variation(ir: NarrativeIR) -> list[Finding]:
    """毛宗岗「犯而不犯」：刻意的重复 + 变化。

    重复的场景类型必须产生变化，否则就是同质化。
    """
    scenes = ir.ordered_scenes()
    out: list[Finding] = []
    for i, a in enumerate(scenes):
        for b in scenes[i + 1 :]:
            ta, tb = _tokens(a.turning_point), _tokens(b.turning_point)
            if not ta or not tb:
                continue
            jac = len(ta & tb) / len(ta | tb)
            if jac >= 0.6:
                same = (
                    a.outcome is b.outcome
                    and a.value_charge_start == b.value_charge_start
                    and a.value == b.value
                )
                if same:
                    out.append(
                        Finding(
                            code="mao_repeat_variation",
                            severity=Severity.WARN,
                            scene_id=b.id,
                            message=(
                                f"与 {a.id} 高度雷同（相似度 {jac:.0%}）且无任何变化"
                            ),
                            suggestion="「犯而不犯」——保留重复但必须变异：换结果、换价值极性、或换承载角色",
                            evidence={"similar_to": a.id, "similarity": round(jac, 2)},
                        )
                    )
    return out


@register("actant_collision")
def actant_collision(ir: NarrativeIR) -> list[Finding]:
    """Greimas：同一个人物占据多个行动元 = 反转信号。"""
    by_entity: dict[str, list[ActantRole]] = {}
    for b in ir.characters.actants:
        by_entity.setdefault(b.entity_id, []).append(b.role)

    out: list[Finding] = []
    for eid, roles in by_entity.items():
        if len(roles) < 2:
            continue
        name = ir.characters.characters.get(eid)
        label = name.name if name else eid
        if ActantRole.SUBJECT in roles and ActantRole.OPPONENT in roles:
            out.append(
                Finding(
                    code="actant_collision",
                    severity=Severity.INFO,
                    entity_id=eid,
                    message=f"「{label}」同时占据 SUBJECT 与 OPPONENT —— 这是反转结构",
                    suggestion="确认这是有意设计；若是，确保 L3 承诺层已登记该转折",
                    evidence={"roles": [r.value for r in roles]},
                )
            )
        elif len(roles) > 3:
            out.append(
                Finding(
                    code="actant_collision",
                    severity=Severity.WARN,
                    entity_id=eid,
                    message=f"「{label}」占据了 {len(roles)} 个行动元，角色功能过载",
                    suggestion="拆分职能到不同角色",
                    evidence={"roles": [r.value for r in roles]},
                )
            )
    return out


@register("focalizer_boundary")
def focalizer_boundary(ir: NarrativeIR) -> list[Finding]:
    """Genette：内聚焦不得越界 —— 聚焦者不能知道他不该知道的事。"""
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if s.focalizer not in s.entities:
            out.append(
                Finding(
                    code="focalizer_boundary",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message=f"聚焦者 {s.focalizer} 不在场景出场实体中",
                    suggestion="把聚焦者加入 entities，或修正 focalizer",
                )
            )
        if s.focalization is Focalization.INTERNAL:
            for e in ir.enigmas:
                if e.resolved_at_scene == s.id and s.focalizer not in e.revealed_to:
                    out.append(
                        Finding(
                            code="focalizer_boundary",
                            severity=Severity.ERROR,
                            scene_id=s.id,
                            message=(
                                f"内聚焦越界：聚焦者 {s.focalizer} 在此场景揭示了"
                                f"谜题「{e.question}」，但他并不知情"
                            ),
                            suggestion="把聚焦者加入 revealed_to，或改用外聚焦/全知聚焦",
                        )
                    )
        if s.focalization is Focalization.EXTERNAL and s.state_deltas:
            out.append(
                Finding(
                    code="focalizer_boundary",
                    severity=Severity.INFO,
                    scene_id=s.id,
                    message="外聚焦场景带有状态增量（涉及角色内部状态）",
                    suggestion="外聚焦只应呈现可观察行为；确认该增量确实可被外部观察到",
                )
            )
    return out


@register("causal_chain_integrity")
def causal_chain_integrity(ir: NarrativeIR) -> list[Finding]:
    """POCL：前置条件必须被先前事件的效果满足。"""
    out: list[Finding] = []
    entities = set(ir.bible.entities)
    entities |= set(ir.characters.characters)

    for ev in ir.plot.events.values():
        for pc in ev.preconditions:
            if pc.kind == "prior_event" and pc.target not in ir.plot.events:
                out.append(
                    Finding(
                        code="causal_chain_integrity",
                        severity=Severity.ERROR,
                        entity_id=ev.id,
                        message=f"前置事件不存在：{pc.target}",
                        suggestion="补齐该事件，或修正 precondition 引用",
                    )
                )
            if pc.kind in ("location", "inventory", "attribute") and pc.target not in entities:
                out.append(
                    Finding(
                        code="causal_chain_integrity",
                        severity=Severity.WARN,
                        entity_id=ev.id,
                        message=f"前置条件引用了未登记的实体：{pc.target}",
                        suggestion="在 Story Bible 中登记该实体",
                    )
                )
        for ef in ev.effects:
            if ef.target not in entities:
                out.append(
                    Finding(
                        code="causal_chain_integrity",
                        severity=Severity.WARN,
                        entity_id=ev.id,
                        message=f"效果作用于未登记的实体：{ef.target}",
                        suggestion="在 Story Bible 中登记该实体",
                    )
                )

    for oid in ir.plot.orphans():
        out.append(
            Finding(
                code="causal_chain_integrity",
                severity=Severity.WARN,
                entity_id=oid,
                message="孤立事件：既无前因也无后果",
                suggestion="连入因果链，或删除",
            )
        )

    # 环检测
    adj: dict[str, list[str]] = {}
    for l in ir.plot.links:
        adj.setdefault(l.src, []).append(l.dst)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {eid: WHITE for eid in ir.plot.events}

    def dfs(u: str, stack: list[str]) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                out.append(
                    Finding(
                        code="causal_chain_integrity",
                        severity=Severity.ERROR,
                        entity_id=v,
                        message=f"因果环：{' → '.join(stack[stack.index(v):] + [v])}",
                        suggestion="因果关系不能成环（除非是刻意的循环叙事，需在承诺层登记）",
                    )
                )
            elif color.get(v, WHITE) == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for eid in ir.plot.events:
        if color[eid] == WHITE:
            dfs(eid, [])
    return out


@register("hook_cadence")
def hook_cadence(ir: NarrativeIR) -> list[Finding]:
    """短剧：集末必须有钩子。

    代理判据（无分集信息时的近似）：场景要么发生价值转折，
    要么新埋了一个未回收的谜题。文档中已标注这是代理指标。
    """
    if ir.medium is not Medium.MICRO_DRAMA:
        return []
    planted: dict[str, str] = {e.planted_at_scene: e.id for e in ir.enigmas}
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        has_hook = s.value_flips or s.id in planted or s.is_branch_point
        if not has_hook:
            out.append(
                Finding(
                    code="hook_cadence",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message="集末无钩子（既无价值转折，也未埋新谜题）",
                    suggestion="在集末加反转或埋钩子 —— 短剧钩子密度应为每 30-60 秒一次",
                )
            )
    return out


@register("paywall_gate_present")
def paywall_gate_present(ir: NarrativeIR) -> list[Finding]:
    """短剧：付费边界是一等结构节点，必须显式存在。"""
    if ir.medium is not Medium.MICRO_DRAMA:
        return []
    gates = [s for s in ir.scenes if s.is_paywall_gate]
    if not gates:
        return [
            Finding(
                code="paywall_gate_present",
                severity=Severity.ERROR,
                message="短剧未标注任何付费卡点",
                suggestion=(
                    "标注付费边界场景（行业惯例约在 8-12 / 26-30 / 60 集；"
                    "这是可配置参数，不是平台公开规格）"
                ),
            )
        ]
    return [
        Finding(
            code="paywall_gate_present",
            severity=Severity.INFO,
            message=f"已标注 {len(gates)} 个付费卡点：{[s.id for s in gates]}",
        )
    ]


def _beat_spans(ir: NarrativeIR) -> list[tuple[float, float]]:
    """把 [0,1] 的故事进度按场景切分，得到每个场景负责的节拍区间。

    为什么不能一个场景只对应一个节拍：
      Save the Cat 有 15 个节拍，但一部长篇只有 6-10 个主要场景。
      「一个场景 = 一个节拍」在数学上就不可能覆盖完，会让校验器永远报警。
      正确的语义是**场景覆盖节拍表上的一段**：场景 i 负责相邻场景进度
      中点之间的那一段。这样 15 个节拍被按比例分摊到 N 个场景上，
      「覆盖完整」才是一个可达的判据。
    """
    scenes = ir.ordered_scenes()
    n = len(scenes)
    if n == 0:
        return []
    if n == 1:
        return [(0.0, 1.01)]
    prog = _progress(ir)
    cuts = [
        (prog[scenes[i].id] + prog[scenes[i + 1].id]) / 2.0 for i in range(n - 1)
    ]
    spans: list[tuple[float, float]] = []
    lo = 0.0
    for c in cuts:
        spans.append((lo, c))
        lo = c
    spans.append((lo, 1.01))
    return spans


@register("template_coverage")
def template_coverage(ir: NarrativeIR) -> list[Finding]:
    """场景是否覆盖了所选结构模板的全部必达节拍。

    判据：场景所负责的节拍区间（见 `_beat_spans`）是否覆盖了全部必达节拍。
    """
    if not ir.beat_template:
        return []
    try:
        tpl = get_template(ir.beat_template)
    except KeyError as exc:
        return [
            Finding(
                code="template_coverage",
                severity=Severity.ERROR,
                message=str(exc),
                suggestion="改用 list_templates() 中的模板 id",
            )
        ]
    spans = _beat_spans(ir)
    covered: set[str] = set()
    for lo, hi in spans:
        for b in tpl.beats:
            b_lo, b_hi = b.position
            # 区间相交即视为被该场景覆盖
            if lo < b_hi and b_lo < hi:
                covered.add(b.id)
    missing = [b.id for b in tpl.beats if b.required and b.id not in covered]
    if missing:
        return [
            Finding(
                code="template_coverage",
                severity=Severity.WARN,
                message=f"模板「{tpl.name}」有 {len(missing)} 个必达节拍未被场景覆盖：{missing}",
                suggestion="补充对应场景，或换用更贴合的结构模板",
                evidence={"template": tpl.id, "missing": missing},
            )
        ]
    return [
        Finding(
            code="template_coverage",
            severity=Severity.INFO,
            message=f"模板「{tpl.name}」节拍覆盖完整（{len(tpl.beats)} 个）",
        )
    ]


@register("thread_budget")
def thread_budget(ir: NarrativeIR) -> list[Finding]:
    """统计价值线分布，供体检报告展示。"""
    c = Counter(s.value for s in ir.scenes)
    if not c:
        return []
    top = "，".join(f"{k}×{v}" for k, v in c.most_common(5))
    return [
        Finding(
            code="thread_budget",
            severity=Severity.INFO,
            message=f"价值线分布：{top}（共 {len(c)} 条）",
            evidence=dict(c),
        )
    ]


@register("outcome_distribution")
def outcome_distribution(ir: NarrativeIR) -> list[Finding]:
    """场景结果分布。全是 yes 的故事没有张力。"""
    scenes = ir.ordered_scenes()
    if not scenes:
        return []
    c = Counter(s.outcome for s in scenes)
    total = len(scenes)
    yes_ratio = c.get(SceneOutcome.YES, 0) / total
    out: list[Finding] = []
    if yes_ratio > 0.6:
        out.append(
            Finding(
                code="outcome_distribution",
                severity=Severity.WARN,
                message=f"场景结果为 YES 的占比 {yes_ratio:.0%}，冲突强度不足",
                suggestion="改用 yes-but / no-and，让代价可见",
            )
        )
    if SceneOutcome.NO_AND not in c and total >= 6:
        out.append(
            Finding(
                code="outcome_distribution",
                severity=Severity.INFO,
                message="全篇没有 no-and（未达成且更糟）的场景",
                suggestion="中段至少需要一次全面溃败来抬高赌注",
            )
        )
    out.append(
        Finding(
            code="outcome_distribution",
            severity=Severity.INFO,
            message="结果分布：" + "，".join(f"{k.value}×{v}" for k, v in c.items()),
            evidence={k.value: v for k, v in c.items()},
        )
    )
    return out


#: 饱和检测的窗口与阈值。窗口粒度是「**可识别装置的场景**」，
#: 不是「全部场景」—— 认不出装置的场景不参与统计，因为把「认不出」
#: 当成一种装置会污染频率分布（它会把任何装置的实际占比稀释）。
_PATTERN_WINDOW = 5
_PATTERN_THRESHOLD = 0.6
#: 判断饱和所需的最少**可识别**场景数。
#:
#: 为什么需要这个下限：`check_saturation` 的频率分母是「窗口内**可识别**场景数」，
#: 不是「窗口内场景数」—— 它拿不到「这一场用了未知装置」这个信息。
#: 于是当全篇只有 1 场能被认出来时，频率恒为 1.0，必然 ≥ 阈值，
#: 于是一个只出现了一次的装置被判成「已饱和」。那不是饱和，那是数据不足。
#:
#: 这与 SKIPPED 是同一条纪律：**证据不足时不判定，而不是判定为通过。**
#: 判据（频率）留在 `check_saturation` 里算，够不够判留在这一层决定 ——
#: 原语只负责算，校验器负责决定要不要拿这个数说话。
_PATTERN_MIN_OBSERVATIONS = 3


@register("pattern_saturation")
def pattern_saturation(ir: NarrativeIR) -> list[Finding]:
    """③ 工艺装置饱和：同一叙事装置在最近 N 场里反复出现。

    出处：
      * Berlyne (1971) *Aesthetics and Psychobiology* —— 唤起理论。
        重复刺激因**习惯化**递减其唤起值：「打脸」第一次有效，第五次无效。
      * Genette (1972) *Discours du récit* —— 叙事频率。把「重复」从单场之内
        提升到**跨章节窗口**来度量。

    为什么需要它：Keel 原先只有逐 storylet 的节奏冷却，**没有手法层面的冷却**。
    后果是 5 个不同的 storylet 可以全是「打脸」而无人报警 ——
    `outcome_distribution` 只看 yes/no/yes_but 的分布，
    `mao_repeat_variation` 只在单场之内查重复。**没有任何一个校验器看得到
    「最近 5 场里有 4 场都在打脸」这件事。**

    装置来源两条通道（双通道思路，与 CHANGES 协议一致）：
      1. 交互式叙事 —— `Storylet.patterns` 显式声明（机器友好，优先）；
      2. 线性叙事 —— 从场景卡的 value / turning_point / conflict / outcome
         关键词反推（兜底）。小说与剧本没有 storylet，只能走这条。

    判据用的是**净命中率**口径：只在超过阈值时报警，健康时零输出。

    ⚠️ 归位关系（这里踩过一次）：`storylet_ids` 是 **`SceneNode` 的字段**，
    不是 `Storylet` 的 —— 一个场景知道「我由哪些 storylet 推进」，
    而 storylet 不知道自己被排到了哪一场。写成 `st.storylet_ids` 会在
    **有 storylet 的 IR 上抛 AttributeError**，而在没有 storylet 的 IR 上
    完全不报错（生成器表达式体根本不求值）——
    于是「干净基线全绿」与「这个分支从来没跑过」可以同时成立。
    现在 `run_all` 会把这类崩溃单独记进 `Report.crashes`，
    `scripts/verify.py` 断言它在所有输入上为空。
    """
    out: list[Finding] = []
    seq: list[str] = []
    owner: dict[str, str] = {}

    #: storylet -> 它推进到的场景。用于把显式声明的装置挂回场景。
    for s in ir.ordered_scenes():
        declared = [
            p
            for st in ir.storylets
            if st.id in s.storylet_ids
            for p in st.patterns
        ]
        pats = declared or infer_patterns(
            " ".join([s.value, s.turning_point, s.conflict, s.outcome.value])
        )
        if not pats:
            continue
        seq.append(pats[0])
        owner[pats[0]] = s.id  # 最后一次出现的场景（后写覆盖）

    # 证据不足时不判定（见 _PATTERN_MIN_OBSERVATIONS）。
    # 没有这一条，一篇只有 1 场能被认出装置的故事会被判「装置已饱和」。
    if len(seq) < _PATTERN_MIN_OBSERVATIONS:
        return out

    for pattern, freq in check_saturation(
        seq, window=_PATTERN_WINDOW, threshold=_PATTERN_THRESHOLD
    ):
        out.append(
            Finding(
                code="pattern_saturation",
                severity=Severity.WARN if freq >= 0.8 else Severity.INFO,
                scene_id=owner.get(pattern),
                message=(
                    f"工艺装置「{pattern}」在最近 {_PATTERN_WINDOW} 个可识别场景里"
                    f"占 {freq:.0%}，已饱和"
                ),
                suggestion=(
                    f"让「{pattern}」休息几场，换用其它装置 —— "
                    "同一手法连续使用会因习惯化而失效（Berlyne 1971）"
                ),
                evidence={
                    "pattern": pattern,
                    "frequency": round(freq, 3),
                    "window": _PATTERN_WINDOW,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# 前提忠实度（Egri premise fidelity）
# ---------------------------------------------------------------------------

#: 取末尾几场作为「结局」—— 前提必须在**结局**兑现，别的场次不算。
_ENDING_WINDOW = 2


@register("premise_fidelity")
def premise_fidelity(ir: NarrativeIR) -> list[Finding]:
    """前提忠实度 —— 结局与承诺层是否还锚定着 Egri 前提。

    **为什么要有这条（外部证据）：**
    PLOTTER（*Planning Beyond Text*, ACL 2026 Findings, arXiv:2604.21253）
    把叙事规划从文本搬到图上之后，在 Narrative / Thematic / Characterization /
    Dramatic Engagement 四个维度的成对比较胜率是 72%–100%，
    **唯独 Premise Fidelity 只有 40% / 14% / 44%**。
    论文自己给出的解释是：**图的迭代精炼会偏离原初前提**。

    这是**图/IR 路线公认的短板**，而且 Keel 正处在这条路线上
    —— `CriticLoop` 会迭代修订，每一次修订都是一次漂移机会。
    这条校验器就是给这个已知短板装一个刹车。

    **它给 `CriticLoop` 的边界提供了第二条理由。**
    原先「只自动修文风、结构类只提提案」的理由是**保护作者意图**（道德层面）。
    现在多了一条**经验层面**的理由：自动改结构不但可能违背意图，
    而且**经验上就是做不好** —— 该领域最强的系统在这个维度上只有 40%。

    **怎么判（以及它不是什么）：**
    用**词汇重叠**作为锚定度的代理指标：把前提切成中文 2-gram / 英文词，
    看这些 token 有多少出现在「结局文本」与「承诺层陈述」里。

    ⚠ **这是代理指标，不是语义理解。** 它测不出「前提被反讽式地颠覆了」
    （那可能正是神来之笔），也测不出「用同义词重写了一遍但精神完全变了」。
    它只能测出一种情况：**结局和承诺层与前提的词汇已经完全没有交集** ——
    这种情况值得作者看一眼，但**不构成「故事跑题了」的证明**。
    按项目铁律 7（不宣称做不到的事），这个限制必须写在结论里，见 evidence。

    **严重度语义：**
      * 结局**和**承诺层都失锚 → WARN（两处独立证据同时指向漂移）
      * 只有一处失锚     → INFO（可能是刻意的，只通报）
      * 两处都锚定       → PASS（不产出结论）
    """
    premise = (ir.commitment.premise or "").strip()
    ptoks = _tokens(premise)
    if not ptoks:
        return []

    # 结局文本：末尾若干场的 转折点 + 正文
    ending = ir.ordered_scenes()[-_ENDING_WINDOW:]
    end_text = " ".join(
        (s.turning_point or "") + " " + (s.prose or "") for s in ending
    )
    etoks = _tokens(end_text)

    # 承诺层：作者自己写下的「必须发生的事」
    ctoks = _tokens(
        " ".join(c.statement for c in ir.commitment.commitments)
    )

    shared_end = ptoks & etoks
    shared_com = ptoks & ctoks

    out: list[Finding] = []
    cov_end = len(shared_end) / len(ptoks)
    cov_com = len(shared_com) / len(ptoks)

    if not shared_end and not shared_com:
        out.append(
            Finding(
                code="premise_fidelity",
                severity=Severity.WARN,
                message=(
                    f"结局与承诺层**都没有**再出现前提「{premise}」的任何成分 "
                    f"（前提 {len(ptoks)} 个词元，两处命中均为 0）"
                ),
                suggestion=(
                    "两处独立证据同时失锚，是漂移的强信号 —— 检查结局是否还在兑现"
                    "前提的因果断言。若是有意的反讽式颠覆，请在承诺层登记，"
                    "否则它与「忘了」在结构上无法区分。"
                ),
                evidence={
                    "premise": premise,
                    "premise_tokens": len(ptoks),
                    "shared_with_ending": 0,
                    "shared_with_commitments": 0,
                    "ending_window": _ENDING_WINDOW,
                    "ending_scenes": [s.id for s in ending],
                    "limitation": "词汇重叠是代理指标，不是语义理解",
                },
            )
        )
    elif not shared_com:
        out.append(
            Finding(
                code="premise_fidelity",
                severity=Severity.INFO,
                message=(
                    f"承诺层没有锚定前提「{premise}」"
                    f"（结局命中 {cov_end:.0%}，承诺层命中 0）"
                ),
                suggestion=(
                    "承诺层是「必须发生什么」的硬约束。它不提前提，"
                    "就意味着没有任何机制阻止后续修订偏离前提。"
                ),
                evidence={
                    "premise": premise,
                    "coverage_ending": round(cov_end, 3),
                    "coverage_commitments": 0.0,
                    "limitation": "词汇重叠是代理指标，不是语义理解",
                },
            )
        )
    elif not shared_end:
        out.append(
            Finding(
                code="premise_fidelity",
                severity=Severity.INFO,
                message=(
                    f"结局没有兑现前提「{premise}」的用词"
                    f"（承诺层命中 {cov_com:.0%}，结局命中 0）"
                ),
                suggestion=(
                    "前提要在**结局**兑现，别处兑现不算。若结局有意颠覆前提，"
                    "请在承诺层写明，否则无法与「跑题」区分。"
                ),
                evidence={
                    "premise": premise,
                    "coverage_ending": 0.0,
                    "coverage_commitments": round(cov_com, 3),
                    "ending_scenes": [s.id for s in ending],
                    "limitation": "词汇重叠是代理指标，不是语义理解",
                },
            )
        )
    return out
