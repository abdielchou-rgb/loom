"""工艺装置分类学 + 窗口化重复检测。

**为什么在 IR 层**（与 `arcs.py` 同一个理由）：这套分类学有两个消费者，
且分属不同层 ——

    keel/runtime/cooldown.py      Director 的模式冷却（生成侧约束）
    keel/validators/structure.py  pattern_saturation 门禁（检查侧约束）

按「跨层共用的叙事概念上移到 IR 层」那条铁律，它必须住在这里。
放在 `runtime/` 会让校验层反向依赖运行时层 —— 而运行时是 2.0 的可选组件，
校验层是 1.0 的核心，让核心依赖可选项是明确的架构倒置。

`arcs.py`（Reagan 六弧线）已经是这个模式的先例：定义在 IR 层，
被校验器 / 提示词 / 桩件三方消费。

── 关于分类学（诚实声明）──────────────────────────────

下方三组是中文网络文学**爽感 / 冲突 / 情感弧线**的类别名，是工程上的
起始分类学，不是从任何具体项目的门禁词表抄来的，也不来自 InkOS（AGPL-3.0）。
它们只是**可替换的标签**；衰减率、阈值、惩罚系数均为本项目独立设计。

── 方法论依据 ─────────────────────────────────────────

  * Berlyne, D. E. (1971) *Aesthetics and Psychobiology* —— 唤起理论。
    重复刺激因**习惯化 (habituation)** 递减其唤起值，这是「同一手法连续使用
    会失效」的机制性解释。
  * Genette, G. (1972) *Discours du récit* —— 叙事频率 (frequency)。
    把「重复」从单场之内提升到**跨章节窗口**来度量，即 `check_saturation`
    的窗口化重复。Keel 现有校验器全是整篇统计，缺「最近 N 场」的视角。
"""

from __future__ import annotations

from collections.abc import Sequence

#: 爽感手法（pleasure devices）。
PLEASURE_TYPES: tuple[str, ...] = (
    "打脸",
    "碾压",
    "降维打击",
    "逆袭",
    "身份揭晓",
    "突破",
    "觉醒",
    "反击",
    "揭穿",
    "震惊",
    "甜",
    "虐",
    "感人",
    "帅",
)

#: 冲突类型（conflict devices）。
CONFLICT_TYPES: tuple[str, ...] = (
    "身份冲突",
    "资源冲突",
    "价值观冲突",
    "关系冲突",
    "生存冲突",
    "认知冲突",
)

#: 情感弧线（emotional arcs）。
EMOTIONAL_ARCS: tuple[str, ...] = (
    "从绝望到希望",
    "从仇恨到和解",
    "从迷茫到坚定",
    "从恐惧到勇气",
    "从自私到牺牲",
)

#: 全部已知模式，顺序即「推荐」的并列决胜顺序。
ALL_PATTERNS: tuple[str, ...] = PLEASURE_TYPES + CONFLICT_TYPES + EMOTIONAL_ARCS

#: 长词优先，避免「打脸」被更短的词先吃掉。
_BY_LENGTH: tuple[str, ...] = tuple(sorted(ALL_PATTERNS, key=len, reverse=True))


def check_saturation(
    sequence: Sequence[str],
    window: int = 5,
    threshold: float = 0.6,
) -> list[tuple[str, float]]:
    """窗口化重复检测：返回在**最近 window 项**里频率达到阈值的模式。

    频率 = 窗口内出现次数 / 窗口实际长度（序列短于 window 时按实际长度归一）。
    判据为 `>= threshold`；低于阈值不报。可脱离运行时，直接作用于任意线性叙事
    （按话语顺序排列的模式序列）。

    例：`["打脸","打脸","觉醒","打脸","打脸"]`，window=5 -> 打脸 4/5=0.8。
    """
    if window <= 0 or not sequence:
        return []
    recent = list(sequence)[-window:]
    denom = len(recent)
    counts: dict[str, int] = {}
    for pattern in recent:
        counts[pattern] = counts.get(pattern, 0) + 1
    saturated = [(p, c / denom) for p, c in counts.items() if c / denom >= threshold]
    saturated.sort(key=lambda kv: -kv[1])
    return saturated


def infer_patterns(text: str) -> list[str]:
    """从一段文本里推断用了哪些工艺装置（子串匹配，按分类学顺序去重）。

    这是**给线性叙事用的兜底通道**：交互式叙事可以在 `Storylet.patterns` 上
    显式声明装置，而小说/剧本没有 storylet，只能从场景卡的关键词反推。

    刻意保守：认不出就返回空列表。空列表 = 该场未使用已知装置，
    不是「这场没有问题」—— 所以 `pattern_saturation` 对空序列不报警。
    """
    if not text:
        return []
    hits = {p for p in _BY_LENGTH if p in text}
    return [p for p in ALL_PATTERNS if p in hits]


__all__ = [
    "ALL_PATTERNS",
    "CONFLICT_TYPES",
    "EMOTIONAL_ARCS",
    "PLEASURE_TYPES",
    "check_saturation",
    "infer_patterns",
]
