"""观众模拟 —— 结构性的流失预测 + 配对比较。

用法（推荐）：

    sim = AudienceSimulator(gen)
    report = sim.run(ir)          # 留存曲线 + 观众原话
    ab = sim.ab(ir_v1, ir_v2)     # 两个版本配对比较（主要用法）

先读 simulator 模块的 docstring —— 里面写清了它不能做什么，
那部分和它能做什么一样重要。
"""

from .personas import (
    BINGE_WEB_NOVEL,
    CASUAL_INTERACTIVE,
    COMMUTER_MOBILE,
    GENRE_CRITIC,
    LIBRARY,
    PRESTIGE_VIEWER,
    Persona,
    get_persona,
    panel,
    select,
)
from .signals import SceneSignals, ir_signals, scene_signals
from .simulator import (
    ABResult,
    AudienceReport,
    AudienceSimulator,
    PersonaVerdict,
    hazard,
    retention_curve,
)

__all__ = [
    "Persona",
    "LIBRARY",
    "get_persona",
    "select",
    "panel",
    "BINGE_WEB_NOVEL",
    "COMMUTER_MOBILE",
    "PRESTIGE_VIEWER",
    "GENRE_CRITIC",
    "CASUAL_INTERACTIVE",
    "SceneSignals",
    "scene_signals",
    "ir_signals",
    "hazard",
    "retention_curve",
    "AudienceSimulator",
    "AudienceReport",
    "PersonaVerdict",
    "ABResult",
]
