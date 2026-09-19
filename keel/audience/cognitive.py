"""认知负荷窗口累加 —— 一个窗口内累积的「读者跟不上」风险。

── 与 hazard 的分工 ─────────────────────────────────────

`keel/audience/simulator.hazard` 是**逐场、无记忆**的：它回答「这一场单看弱不弱」。
本模块回答的是互补的问题：「这一串场景每一场单看都没问题，
但连着读下来会不会把读者压垮」。

两者是不同结构，缺一不可：

    单场 hazard 高  ->  这一场本身有问题        （该场重写）
    窗口累加负荷高  ->  每场都合格，但它们挤在一起（该摊开）

后者纯规则可算，不需要任何模型判断。

── 输入维度来自哪里 ────────────────────────────────────

事件索引模型（Zwaan, Langston & Graesser 1995, Psychological Science 6(5)；
Zwaan & Radvansky 1998, Psychological Bulletin 123(2)）主张：读者理解叙事时
沿五个情境维度建立索引 —— 时间 / 空间 / 主角 / 因果 / 意图。
**某一维度上的不连续会触发事件边界**，读者必须重建情境模型，因而付出加工代价。

Magliano, Miller & Zwaan (2001, Applied Cognitive Psychology 15(5): 533-545)
在影片理解上做了直接检验：时间与空间的跳变确实带来可测量的理解代价。
事件分割理论（Zacks, Speer, Swallow, Braver & Reynolds 2007,
Psychological Bulletin 133(2)）给出同一现象的记忆侧证据。

所以本模块**选取的维度**是有出处的：

    focalizer 变化    -> 主角 / 视角维度不连续
    fabula_time 跳变  -> 时间维度不连续（跳得越远，代价越大）
    location 变化     -> 空间维度不连续
    entities 新入场   -> 主角维度不连续
    flashback 信号    -> 时间倒错，需要在时间轴上重新定位

── ⚠️ 权重是先验（prior），不是测出来的常数 ────────────────

必须说清楚：**上面那些文献支撑的是「哪些维度值得算」，不是「每个维度值几分」。**
`CognitivePriors` 里每一个数字都是**先验** —— 是待校准的假设，
不是从任何论文里读出来的系数，也不是经过实证拟合的公式。
本模块刻意**不**声称自己实现了某个「学术加权公式」。

把它们写成显式的具名常量、并允许调用方整块替换，正是为了让它们
可以被真实数据重新校准，而不是被当成科学结论引用。
`scene_load` / `windowed_loads` / `scan_ir` 都接受 `priors=` 参数。

最明显的一处自证就在常量表里：`time_magnitude_cap = 3.0` 会把「年」
（原始先验 ×10）和「月」（原始先验 ×3）压成同一个乘数 ——
两者在本模块里价格完全相同。这是按需求原样实现的，但它本身就说明
这组数字没经过校准：如果年份跳变确实该更贵，把 cap 提到 ≥10 即可。
**一个能被一句话改掉的系数，不该被包装成科学。**

── 输出 ────────────────────────────────────────────────

`scene_load` 返回 `LoadBreakdown`（total + parts）。`parts` 只列**非零**项 ——
一个说不清来源的数字不可行动，所以每个贡献都单独留痕。

`scan_ir` 对**每一场**都出 Finding：默认 `Severity.INFO`（负荷画像），
累计值**严格大于** threshold 才升级为 `Severity.WARN`。
这条策略是刻意的：INFO 是通报，WARN 才是门禁。
逐场都报 WARN 会把「正常起伏」误报成「问题」，等于噪声。

── 不做的事 ────────────────────────────────────────────

* 不调用任何模型。全部由 IR 字段确定性算出（与 signals.py 同一原则）。
* 不做跨章数值 / 事实一致性 —— 那是 `keel.audit.csn` 的职责。
* 不注册进 `keel.validators` 的 registry —— 接线由调用方负责
  （注册与 REQUIRES 声明不在本模块范围内）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ir.enums import Frequency, Severity
from ..ir.models import NarrativeIR, SceneNode
from ..validators.base import Finding


# ---------------------------------------------------------------------------
# 先验常量块 —— 唯一需要校准的地方，全部集中在此
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CognitivePriors:
    """认知负荷模型的先验系数。

    **这些数字全部是先验，不是实证常数。** 改这里 = 重新设定假设；
    接真实读者数据后应当整块替换（`scene_load(..., priors=...)`）。

    每个字段都写明它来自哪个维度的哪条假设，以及该假设的来源性质：
    有文献支撑的写文献，没有的写「先验」。
    """

    # -- 跳变成本：文献支撑「该维度要算」，数值无出处 --
    pov_switch: float = 4.0
    """视角/聚焦者切换。事件索引模型的「主角」维度（先验权重）。"""

    time_jump: float = 2.0
    """时间跳变的基础成本，再乘以下方的量级系数（先验权重）。"""

    location_change: float = 2.0
    """空间不连续。Magliano et al. 2001 支持空间跳变有代价（先验权重）。"""

    new_character: float = 3.0
    """角色**新入场**的基础成本（先验权重）。"""

    flashback: float = 3.0
    """闪回类信号（显式闪回 / 一事多讲 / 多事一讲）（先验权重）。"""

    # -- 时间量级：原始先验 ×10 / ×3，被 cap 截断 --
    time_year: float = 10.0
    time_month: float = 3.0
    time_magnitude_cap: float = 3.0
    """量级乘数上限。**默认值会把「年」压到与「月」同价**，见模块 docstring。"""

    # -- 折扣与分类阈值 --
    returning_character_factor: float = 0.5
    """已在前面场景出现过的角色重新入场 -> 成本减半（先验折扣）。"""

    day_year_threshold: int = 365
    """无 label 时，fabula day 差 >= 此值判为「年」量级（先验阈值）。"""

    day_month_threshold: int = 30
    """无 label 时，fabula day 差 >= 此值判为「月」量级（先验阈值）。"""


#: 默认先验。调用方可以整块替换以重新校准。
DEFAULT_PRIORS = CognitivePriors()

#: 累计负荷超过此值即升级为 WARN。同样是先验。
DEFAULT_THRESHOLD = 12.0

#: 默认窗口宽度（场数，含当前场）。
DEFAULT_WINDOW = 3

#: Finding 的 code。未注册进 registry —— 接线由调用方负责。
CODE = "cognitive_load_window"

#: parts 的键名，固定顺序便于阅读与断言。
PART_KEYS = (
    "pov_switch",
    "time_jump",
    "location_change",
    "new_character",
    "flashback",
)


@dataclass
class LoadBreakdown:
    """单场负荷的可解释分解。

    `total` 是给门禁用的数；`parts` 是给人看的账 ——
    只有能指到具体因子的报告才是可行动的。
    """

    total: float
    parts: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 单场负荷
# ---------------------------------------------------------------------------


def _time_kind(
    scene: SceneNode, prev: SceneNode, priors: CognitivePriors
) -> str | None:
    """判定时间跳变的量级类别；无跳变返回 None。

    label 优先（作者显式写了「三年前」就该被尊重），
    否则按 fabula day 的差值分类。差值取绝对值 —— 时间倒流同样是跳变。
    """
    delta = abs(scene.fabula_time.day - prev.fabula_time.day)
    if delta == 0:
        return None
    label = scene.fabula_time.label or ""
    if "年" in label:
        return "year"
    if "月" in label:
        return "month"
    if delta >= priors.day_year_threshold:
        return "year"
    if delta >= priors.day_month_threshold:
        return "month"
    return "day"


def _is_flashbackish(scene: SceneNode) -> bool:
    """闪回类信号。

    三类都要求读者在时间轴上重新定位：
      is_flashback          显式闪回
      REPETITIVE            同一事件讲多次（罗生门式重述）
      ITERATIVE             多次事件讲一次（「那年夏天他每天…」的时间压缩）
    """
    return scene.fabula_time.is_flashback or scene.frequency in (
        Frequency.REPETITIVE,
        Frequency.ITERATIVE,
    )


def scene_load(
    scene: SceneNode,
    seen_characters: set[str],
    prev_scene: SceneNode | None,
    priors: CognitivePriors = DEFAULT_PRIORS,
) -> LoadBreakdown:
    """单场认知负荷（相对前一场）。

    Args:
        scene: 待评估场景。
        seen_characters: **本场之前**已出现过的角色 id 集合。
        prev_scene: 话语顺序上的前一场；None 表示这是首场。
        priors: 先验系数，可整块替换以重新校准。

    Returns:
        LoadBreakdown。`parts` 只包含非零项。

    规则（全部为先验，见模块 docstring）：
      * 角色只统计**新入场**的（本场有、上一场没有）。
        连续在场的角色不需要重新索引，因此零成本 ——
        否则每个场景都会恒有一份角色成本，窗口累加会被基线噪声淹没。
      * 已在更早场景出现过的角色重新入场，成本 × `returning_character_factor`。
      * 地点为 None 视为「未标注」而非「换了地方」，不判定变化（保守）。
      * 首场无前置：视角 / 时间 / 空间三类跳变都无从谈起。
    """
    parts: dict[str, float] = {}

    prev_entities: set[str] = set(prev_scene.entities) if prev_scene else set()

    if prev_scene is not None:
        # 视角维度：聚焦者变化，或聚焦模式（内/外/全知）变化
        if (
            scene.focalizer != prev_scene.focalizer
            or scene.focalization != prev_scene.focalization
        ):
            parts["pov_switch"] = priors.pov_switch

        # 时间维度
        kind = _time_kind(scene, prev_scene, priors)
        if kind is not None:
            raw = {"year": priors.time_year, "month": priors.time_month}.get(
                kind, 1.0
            )
            parts["time_jump"] = priors.time_jump * min(
                raw, priors.time_magnitude_cap
            )

        # 空间维度：两端都标注了才比较
        if (
            scene.location is not None
            and prev_scene.location is not None
            and scene.location != prev_scene.location
        ):
            parts["location_change"] = priors.location_change

    # 主角维度：新入场角色
    entrants = {e for e in scene.entities if e not in prev_entities}
    if entrants:
        cost = 0.0
        for e in sorted(entrants):
            factor = (
                priors.returning_character_factor
                if e in seen_characters
                else 1.0
            )
            cost += priors.new_character * factor
        parts["new_character"] = cost

    # 时间倒错
    if _is_flashbackish(scene):
        parts["flashback"] = priors.flashback

    nonzero = {k: v for k, v in parts.items() if v != 0.0}
    return LoadBreakdown(total=sum(nonzero.values()), parts=nonzero)


# ---------------------------------------------------------------------------
# 窗口累加
# ---------------------------------------------------------------------------


def _load_series(
    ir: NarrativeIR, priors: CognitivePriors
) -> list[tuple[SceneNode, LoadBreakdown]]:
    """逐场算出负荷，并维护「此前见过的角色」集合。

    `windowed_loads` 与 `scan_ir` 共用此函数 —— 累加逻辑只能有一份，
    否则两个入口迟早会漂移。
    """
    out: list[tuple[SceneNode, LoadBreakdown]] = []
    seen: set[str] = set()
    prev: SceneNode | None = None
    for s in ir.ordered_scenes():
        out.append((s, scene_load(s, seen, prev, priors=priors)))
        seen.update(s.entities)
        prev = s
    return out


def windowed_loads(
    ir: NarrativeIR,
    window: int = DEFAULT_WINDOW,
    priors: CognitivePriors = DEFAULT_PRIORS,
) -> list[tuple[str, float]]:
    """逐场给出**窗口内累计**负荷。

    第 i 场的累计 = 第 i-window+1 场到第 i 场的单场负荷之和
    （窗口不足时从头开始，即左边界截断而非补零）。

    Args:
        window: 窗口宽度（场数，含当前场）。必须 >= 1。

    Returns:
        [(scene_id, 累计负荷)]，按话语顺序。

    window=1 时退化为逐场负荷 —— 这是与 `hazard` 对比的基线。
    """
    if window < 1:
        raise ValueError(f"window 必须 >= 1，得到 {window!r}")

    series = _load_series(ir, priors)
    totals = [bd.total for _, bd in series]
    out: list[tuple[str, float]] = []
    for i, (s, _) in enumerate(series):
        lo = max(0, i - window + 1)
        out.append((s.id, sum(totals[lo : i + 1])))
    return out


def _window_parts(
    series: list[tuple[SceneNode, LoadBreakdown]], lo: int, hi: int
) -> dict[str, float]:
    """窗口内各因子的合计 —— 让「为什么超线」能指到因子级。"""
    agg: dict[str, float] = {}
    for j in range(lo, hi + 1):
        for k, v in series[j][1].parts.items():
            agg[k] = round(agg.get(k, 0.0) + v, 6)
    return agg


def scan_ir(
    ir: NarrativeIR,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
    priors: CognitivePriors = DEFAULT_PRIORS,
) -> list[Finding]:
    """扫描整部 IR，逐场产出认知负荷 Finding。

    严重度策略（刻意如此）：
        累计 <= threshold  ->  Severity.INFO   负荷画像，不参与门禁
        累计  > threshold  ->  Severity.WARN   窗口累加过载

    每一场都出 Finding 而不是只出超标的那些：一份**只有问题**的报告
    看不出负荷是怎么堆起来的。信息量在曲线本身。

    阈值比较是**严格大于** —— 恰好等于 threshold 不报警。
    """
    series = _load_series(ir, priors)
    totals = [bd.total for _, bd in series]
    out: list[Finding] = []

    for i, (s, bd) in enumerate(series):
        lo = max(0, i - window + 1)
        span = i - lo + 1
        cum = sum(totals[lo : i + 1])
        over = cum > threshold
        wparts = _window_parts(series, lo, i)

        if over:
            top = sorted(wparts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
            top_s = "、".join(f"{k} {v:.1f}" for k, v in top)
            suggestion = (
                f"窗口内主要来源：{top_s}。考虑拆场、补一段过渡，"
                "或把跳变改成渐进交代。"
            )
        else:
            suggestion = None

        out.append(
            Finding(
                code=CODE,
                severity=Severity.WARN if over else Severity.INFO,
                scene_id=s.id,
                message=(
                    f"最近 {span} 场累计认知负荷 {cum:.1f}"
                    f"（阈值 {threshold:.1f}，本场 {bd.total:.1f}）"
                ),
                suggestion=suggestion,
                evidence={
                    "total": cum,
                    "scene_total": bd.total,
                    "span": span,
                    "window": window,
                    "threshold": threshold,
                    "parts": dict(bd.parts),
                    "window_parts": wparts,
                },
            )
        )
    return out
