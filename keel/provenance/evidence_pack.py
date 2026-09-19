"""证据包导出 —— 申诉材料（P5 · 证据包）。

用户可能需要**辩护**一份作品的「人类作者身份 / AI 参与程度」。
本模块产出一个**可重放（replayable）的证据包**：一个 `.zip`，内含

    ir.json            IR 快照（规范序列化，可离线重算）
    process_report.md  创作过程报告（主张证据：人做了哪些判断）
    decisions.json     决策日志（ir.proposals 的结构化修订提案）
    MANIFEST.json      指纹 + 参数 + 重放说明
    README.txt         自包含声明 + 「以主管部门口径为准」免责

**可重放性（诚实铁律 22）**：包里的 `ir.json` 与内存中的 `ir` 是同一份
数据的无损往返（`model_dump(mode="json")` → `model_validate`），因此对打包后的
`ir.json` 再跑 `run_all(ir).score()` 必然得到与原始 `ir` 相同的分数。
这个性质由测试断言，不是口头承诺。

指纹复用 `keel/render/export.py::work_fingerprint` 的**同一套**规范 JSON + SHA-256
算法，使本模块产出的指纹与报告导出（P5 报告）完全一致 —— 同一作品、同一参数，
无论走哪条导出路径，指纹都相同。
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

from ..ir.models import NarrativeIR
from .process import build_process_report

#: 复用 export.py 的规范哈希（同一算法 → 跨模块指纹一致）。
#: 文档见模块 docstring。若无法干净导入，应在此复制 export.py 的
#: `_canonical` + SHA-256 逻辑（并标注「mirrors export.py」），不得另起一套。
from ..render.export import work_fingerprint  # noqa: F401  (reused, not redefined)


def _write_if_present(zf: zipfile.ZipFile, name: str, content: str) -> None:
    """往 zip 里写一个 UTF-8 文本成员。"""
    zf.writestr(name, content.encode("utf-8"))


def build_evidence_pack(
    ir: NarrativeIR,
    out_dir: str,
    params: dict | None = None,
) -> str:
    """构建一个可重放证据包 `.zip`，返回其完整路径。

    `out_dir/evidence_pack_<fingerprint>.zip`，包含 ir.json / process_report.md /
    decisions.json / MANIFEST.json / README.txt。

    任何单一步骤（如过程报告渲染）失败都**不会**让整个函数崩溃 —— 出错的那一项
    改为写入一条清晰的说明，其余成员照常打包（申诉材料宁可少一项、不能整包炸）。
    """
    fingerprint = work_fingerprint(ir, params)
    out_path = Path(out_dir) / f"evidence_pack_{fingerprint}.zip"

    # -- ir.json：规范序列化（mode="json", indent=2），无损往返的基准 --
    ir_json = ir.model_dump(mode="json")
    ir_text = json.dumps(ir_json, ensure_ascii=False, indent=2)

    # -- process_report.md：创作过程报告（主张证据）--
    report_md: str
    try:
        report = build_process_report(ir)
        report_md = report.to_markdown()
    except Exception as exc:  # 宁可降级为说明，也不让整包失败
        report_md = (
            "# 创作过程报告（未能生成）\n\n"
            f"本证据包在生成创作过程报告时遇到错误：`{type(exc).__name__}: {exc}`。\n"
            "其余成员（ir.json / decisions.json / MANIFEST.json）已正常打包。\n"
            "请在能运行 Keel 的环境中重新导出以补全此报告。"
        )

    # -- decisions.json：决策日志（ir.proposals 是 Diff 列表）--
    decisions: dict
    if ir.proposals:
        decisions = {
            "proposals": [d.model_dump(mode="json") for d in ir.proposals]
        }
    else:
        decisions = {"proposals": []}
    decisions_text = json.dumps(decisions, ensure_ascii=False, indent=2)

    # -- MANIFEST.json：指纹 + 参数 + 重放说明 --
    manifest = {
        "fingerprint": fingerprint,
        "params": params,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "replay": (
            "re-run `from keel.validators.base import run_all; "
            "run_all(ir).score()` on ir.json to reproduce the score"
        ),
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)

    # -- README.txt：自包含声明 + 免责 --
    readme = (
        "本文件是 Keel 生成的「作品证据包」，用于创作过程留痕与合规申诉举证。\n"
        "它**自包含**：包内的 ir.json（作品快照）、process_report.md（创作过程报告）、"
        "decisions.json（决策日志）、MANIFEST.json（指纹与重放说明）共同构成一份可在"
        "断网环境下离线核验的材料。对 ir.json 重新运行 Keel 的校验器"
        "（`run_all(ir).score()`）即可复现 MANIFEST 中记录的评分，证明评分与作品内容一致、\n"
        "未被事后篡改。\n"
        "需特别声明：本证据包由 Keel 自动生成，其结论**仅供参考**，**不构成**法律效力或"
        "任何官方认定；作品的人类作者身份 / AI 参与程度的认定，**以主管部门口径为准**。"
    )

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_if_present(zf, "ir.json", ir_text)
        _write_if_present(zf, "process_report.md", report_md)
        _write_if_present(zf, "decisions.json", decisions_text)
        _write_if_present(zf, "MANIFEST.json", manifest_text)
        _write_if_present(zf, "README.txt", readme)

    return str(out_path)
