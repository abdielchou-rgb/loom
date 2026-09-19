"""情感弧线的规范定义。

出处：Reagan, Mitchell, Kiley, Danforth & Dodds (2016),
*The emotional arcs of stories are dominated by six basic shapes*,
EPJ Data Science 5:31 —— 用约 1300 部作品的经验数据归纳出的六种基本形状。
这是 Keel 里「弧线」这个概念的唯一权威定义。

**为什么放在 IR 层，而不是校验器层**

弧线是**叙事事实**，不是某个校验器的实现细节。有三个消费方，且层次不能倒：

    ir/arcs.py                      唯一定义（本文件）
      ├─ validators/structure.py      判断文本是否贴合声明的弧线
      ├─ llm/prompts.py               把弧线形状写进提示词（否则模型无从遵循）
      └─ llm/mock.py                  桩件按弧线产出 emotion 值

放在校验器里会让后两者反向依赖校验层。

这个上移不是洁癖，是被 fixture 库逼出来的。原来的实现里：

  * `_ARC_ANCHORS` 只存在于 `validators/structure.py`（校验层）
  * STRUCTURE 提示词**从头到尾没有告诉模型声明的是哪条弧线**，
    却要求它填 `emotion(-1..1)`
  * 桩件把 emotion 写死成一条单调上升的直线，与 `arc_shape` 完全无关

结果是：流水线自己产出的 IR 过不了自己的 `emotion_curve_match`——
一个「要求了却没给依据」的断层。把它放到 IR 层，才有了统一的修补位置。
"""

from __future__ import annotations

from .enums import ArcShape

#: 弧线 -> 锚点序列 [(进度 0..1, 情感值 -1..1)]。锚点之间线性插值。
ARC_ANCHORS: dict[ArcShape, list[tuple[float, float]]] = {
    ArcShape.RAGS_TO_RICHES: [(0.0, -1.0), (1.0, 1.0)],
    ArcShape.TRAGEDY: [(0.0, 1.0), (1.0, -1.0)],
    ArcShape.MAN_IN_A_HOLE: [(0.0, 0.0), (0.42, -1.0), (1.0, 0.6)],
    ArcShape.ICARUS: [(0.0, -0.6), (0.5, 1.0), (1.0, -1.0)],
    ArcShape.CINDERELLA: [(0.0, -0.4), (0.35, 0.8), (0.6, -0.8), (1.0, 1.0)],
    ArcShape.OEDIPUS: [(0.0, 0.6), (0.35, -0.8), (0.6, 0.8), (1.0, -1.0)],
}

#: 弧线的自然语言描述。写进提示词 —— 模型要能照着它塑形，光给一个枚举名没用。
ARC_DESCRIPTIONS: dict[ArcShape, str] = {
    ArcShape.RAGS_TO_RICHES: "持续上升：处境由坏变好，全程不回撤",
    ArcShape.TRAGEDY: "持续下降：处境由好变坏，全程不回升",
    ArcShape.MAN_IN_A_HOLE: "先跌后起：约 40% 处触底，结尾回升（不必回到原点）",
    ArcShape.ICARUS: "先起后跌：约 50% 处登顶，此后一路下滑",
    ArcShape.CINDERELLA: "起—跌—起：约 35% 处上升，60% 处跌落，结尾升至最高",
    ArcShape.OEDIPUS: "跌—起—跌：约 35% 处触底，60% 处升至最高，结尾跌至最低",
}

#: 采样网格。判断「声明弧线的转折点在哪」时用。
GRID: tuple[float, ...] = tuple(i / 40 for i in range(41))


def interpolate(anchors: list[tuple[float, float]], x: float) -> float:
    """在锚点之间线性插值。区间外取端点值（不外推）。"""
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]


def arc_curve(arc_shape: ArcShape, progress: float) -> float:
    """声明弧线在给定进度处的目标情感值。"""
    return interpolate(ARC_ANCHORS[arc_shape], max(0.0, min(1.0, progress)))


def third_of(x: float) -> int:
    """把 [0,1] 三等分，返回所在段的序号（0 / 1 / 2）。"""
    return min(2, int(x * 3))


def interior_extremum(
    values: list[float],
    positions: list[float],
    *,
    margin: float = 0.05,
) -> tuple[str, float] | None:
    """曲线的**内部**极值：类型（"min"/"max"）与所在位置。

    **端点极值不算。** 单调曲线的极值必然落在端点上，那说明这条曲线
    没有转折点。而 Reagan 六弧线之间的区分恰恰在于转折点在哪里：
    `man_in_a_hole` 与 `rags_to_riches` 的区别不是「与某条直线的相关度」，
    而是「中间有没有一个谷」。

    为什么需要这个判据（真实缺陷，由 fixture 库抓到）：
    一条单调上升的情感曲线与 `man_in_a_hole` 的声明弧线的 Pearson
    相关度高达 **r = 0.49** —— 因为「从谷底回升」那一段占了多数采样点，
    足以把相关系数拉正。仅凭 `r > 0.3` 就会判「匹配度良好」，
    于是**完全没有谷的故事通过了谷型弧线的检查**。

    返回 None 表示曲线在内部没有极值（单调，或极值落在两端）。
    """
    n = len(values)
    if n < 3:
        return None
    cands: list[tuple[str, float, float]] = []
    for kind, idx in (
        ("min", min(range(n), key=lambda i: values[i])),
        ("max", max(range(n), key=lambda i: values[i])),
    ):
        p = positions[idx]
        if margin < p < 1.0 - margin:
            cands.append((kind, p, values[idx]))
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0][0], cands[0][1]
    # 两者都落在内部：取偏离中位更远的那个 —— 更显著的转折
    mid = (max(values) + min(values)) / 2.0
    kind, p, _ = max(cands, key=lambda c: abs(c[2] - mid))
    return kind, p


def declared_extremum(arc_shape: ArcShape) -> tuple[str, float] | None:
    """声明弧线的内部转折点。单调弧线（rags_to_riches / tragedy）返回 None。"""
    anchors = ARC_ANCHORS[arc_shape]
    return interior_extremum(
        [interpolate(anchors, g) for g in GRID], list(GRID)
    )


__all__ = [
    "ARC_ANCHORS",
    "ARC_DESCRIPTIONS",
    "GRID",
    "arc_curve",
    "declared_extremum",
    "interior_extremum",
    "interpolate",
    "third_of",
]
