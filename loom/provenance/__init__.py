"""溯源与合规计量。

三样东西，同源但**目的不同**：

    ProvenanceLedger   谁生成了这段文字   → 合规溯源（AI 参与度必须可计量）
    DecisionTelemetry  作者如何裁决提案   → 产品调参（采纳率 + 按维度分布）
    build_process_report                 → **申诉举证**（把前两者拼成
                                          一份「人类做了哪些判断」的报告）

把「记录」和「指标」混在一起，会让指标被记录的持久化问题绑架 ——
所以遥测是纯内存、纯函数式读取，且**不碰时钟**。

第三项为什么单独存在：`ProvenanceLedger` 记的是**免责证据**
（「这段不是 AI 写的」），而申诉要的是**主张证据**
（「这些判断是人类做的」）。前者只能说明「剩下的不是 AI 写的」，
说不出人做了什么。详见 `process.py` 的模块 docstring。

第四项：**觉察回显**（`awareness`）与第三项**用同一份数据，出口不同**。
`process` 是**申诉时**导出的材料；`awareness` 是**写作过程中**回显的一行字。
这个区分来自 CHI 2026 *Reactive Writing*：作者**察觉不到** AI 对自己方向的影响，
却感觉完全掌控 —— 所以「你做了多少判断」必须在**当时**可见，
三天后再看到，写作过程并不会被改变。详见 `awareness.py` 的模块 docstring。
"""

from .awareness import awareness_block, awareness_line, counts, scenes_touched
from .evidence_pack import build_evidence_pack
from .meter import ParticipationReport, ProvenanceLedger
from .process import CreativeProcessReport, Judgement, build_process_report
from .telemetry import DecisionRecord, DecisionTelemetry

__all__ = [
    "ParticipationReport",
    "ProvenanceLedger",
    "DecisionRecord",
    "DecisionTelemetry",
    "CreativeProcessReport",
    "Judgement",
    "build_process_report",
    "counts",
    "scenes_touched",
    "awareness_line",
    "awareness_block",
    "build_evidence_pack",
]
