"""事件冷却矩阵：手法 / 母题层面的生成侧约束（craft-device cooldown）。

── 方法论来源 ──────────────────────────────────────────

本模块补一个**真实存在的覆盖缺口**：Director 只有逐 storylet 的节奏冷却，
没有手法层面的冷却，于是五个不同的 storylet 可以全是「打脸」而无人报警
（`outcome_distribution` 只看 yes/no/yes_but，`mao_repeat_variation` 只看单场
之内的重复）。两条外部依据：

  1. Berlyne, D. E. (1971) *Aesthetics and Psychobiology* —— 唤起理论
     (arousal theory)。重复刺激因**习惯化 (habituation)** 而递减其唤起值，
     这是「同一手法连续使用会失效」的机制性解释。本模块用 `decay ** steps`
     的指数衰减建模习惯化：新近用过的手法冷却值高，随叙事推进按几何速率回落。

  2. Genette, G. (1972) *Discours du récit* —— 叙事频率 (frequency)。
     把「重复」从单场之内提升到**跨章节窗口**来度量，正是 `check_saturation`
     的窗口化重复 (windowed repetition)。Loom 现有校验器全是整篇统计，缺
     「最近 N 场」的视角；该函数可脱离运行时独立用于线性叙事。

── 关于分类学（诚实声明）──────────────────────────────

下方 PLEASURE_TYPES / CONFLICT_TYPES / EMOTIONAL_ARCS 是中国网络文学爽感与
冲突的**类别名**（工程上的起始分类学），不是从任何具体项目的门禁词表抄来的，
也不来自 InkOS（AGPL-3.0）。它们只是可替换的标签；衰减率、阈值、惩罚系数均为
本项目的独立设计，依据是上述两条来源的**定性结论**，非从别处搬来的数字。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..ir.devices import (
    ALL_PATTERNS,
    CONFLICT_TYPES,
    EMOTIONAL_ARCS,
    PLEASURE_TYPES,
    check_saturation,
)

# 分类学与 `check_saturation` 已上移到 `loom/ir/devices.py`（见该文件说明）。
# 此处重新导出，`from loom.runtime.cooldown import ALL_PATTERNS` 仍然可用 ——
# 单一真源只有一处，这里只是转发。
__all__ = [
    "ALL_PATTERNS",
    "CONFLICT_TYPES",
    "EMOTIONAL_ARCS",
    "PLEASURE_TYPES",
    "EventCooldownMatrix",
    "check_saturation",
]


class EventCooldownMatrix:
    """记录手法使用、按叙事推进衰减、并给出冷却查询。

    语义：某模式的**冷却值**越高，说明它刚被用得越密，越应该让它「休息」。
    冷却值 = 历史记录次数按 `decay ** steps` 指数衰减后的残余量。
    """

    def __init__(self, decay: float = 0.7) -> None:
        self.decay = decay
        self.matrix: dict[str, float] = {}

    def record_usage(self, pattern: str) -> None:
        """记录一次手法使用（累加 1.0，而非覆盖）。"""
        self.matrix[pattern] = self.matrix.get(pattern, 0.0) + 1.0

    def advance_time(self, steps: int = 1) -> None:
        """推进叙事时间：所有模式的冷却值乘以 `decay ** steps`。

        `steps<=0` 视为不推进（避免把冷却值反向放大）。
        """
        if steps <= 0:
            return
        factor = self.decay**steps
        for key in self.matrix:
            self.matrix[key] *= factor

    def get_cooldown(self, pattern: str) -> float:
        """当前冷却值；从未记录过的模式为 0.0。"""
        return self.matrix.get(pattern, 0.0)

    def get_hot_patterns(self, threshold: float = 0.5) -> list[tuple[str, float]]:
        """过热模式（应当休息），按冷却值降序；判据为 `>= threshold`。"""
        hot = [(p, v) for p, v in self.matrix.items() if v >= threshold]
        hot.sort(key=lambda kv: -kv[1])
        return hot

    def get_recommendations(self, n: int = 3) -> list[str]:
        """建议接下来使用的模式：全分类学里冷却值最低的 n 个。

        候选集是**完整分类学**（而非仅已用过的模式）——因为从未用过的模式
        冷却为 0，恰恰最该被推荐，这正是「打破母题单调」的用意。
        并列时按分类学顺序决胜（稳定排序）。
        """
        candidates = list(dict.fromkeys(ALL_PATTERNS + tuple(self.matrix)))
        candidates.sort(key=self.get_cooldown)
        return candidates[: max(0, n)]

    @staticmethod
    def check_saturation(
        sequence: Sequence[str],
        window: int = 5,
        threshold: float = 0.6,
    ) -> list[tuple[str, float]]:
        """窗口化重复检测。**实现已上移到 `loom/ir/devices.py`**，此处仅转发。

        保留这个静态方法是向后兼容：调用点与既有测试无需改动，
        而算法只有一处实现（校验层的 `pattern_saturation` 直接用同一个函数）。
        """
        return check_saturation(sequence, window=window, threshold=threshold)
