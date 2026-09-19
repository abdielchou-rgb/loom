from .anti_slop import SlopHit, SlopReport, scan_ir, scan_slop, slop_findings
from .craft import (
    ControlHit,
    ControlReport,
    MicroTensionReport,
    ParagraphTension,
    RealityReport,
    ShowTellReport,
    TellHit,
    control_findings,
    micro_tension_findings,
    reality_findings,
    scan_control,
    scan_micro_tension,
    scan_reality,
    scan_show_dont_tell,
    show_dont_tell_findings,
)

#: craft 的 scan_ir 与 anti_slop 的 scan_ir 同名。**不能覆盖** —— 前者扫工艺，
#: 后者扫 AI 味，两个都要能用，故此处给 craft 的起别名。
from .craft import scan_ir as scan_craft_ir

from .selfcheck import (  # noqa: E402
    DIMENSIONS,
    REGULATIONS,
    CheckItem,
    SubmissionChecklist,
    content_id,
    implicit_metadata,
    pre_submit_check,
    required_labels,
)

__all__ = [
    "ControlHit",
    "ControlReport",
    "DIMENSIONS",
    "MicroTensionReport",
    "ParagraphTension",
    "REGULATIONS",
    "RealityReport",
    "CheckItem",
    "ShowTellReport",
    "SlopHit",
    "SlopReport",
    "SubmissionChecklist",
    "TellHit",
    "content_id",
    "control_findings",
    "implicit_metadata",
    "micro_tension_findings",
    "pre_submit_check",
    "reality_findings",
    "required_labels",
    "scan_control",
    "scan_craft_ir",
    "scan_ir",
    "scan_micro_tension",
    "scan_reality",
    "scan_show_dont_tell",
    "scan_slop",
    "show_dont_tell_findings",
    "slop_findings",
]
