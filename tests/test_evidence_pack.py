"""证据包导出测试（P5 · 证据包）。

RED-first：先写断言，确认逻辑正确后再让它 GREEN。

核心不变量（诚实铁律 22）：
  * 包内 ir.json 是内存 IR 的无损往返，对打包后的 ir.json 重跑
    `run_all(ir).score()` 必须等于对原始 ir 的分数 —— 否则「可重放」是空话。
  * 改动作品内容（哪怕一个场景的正文）必须改变指纹，使 MANIFEST 与内容绑定。
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# 让本文件既能 `python tests/test_*.py` 直接跑，也能被 unittest discover 发现。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loom.ir.enums import Medium
from loom.ir.models import NarrativeIR
from loom.provenance.evidence_pack import build_evidence_pack
from loom.validators.base import run_all

from tests.fixtures import build_clean_ir


class EvidencePackTest(unittest.TestCase):
    def setUp(self) -> None:
        # 注意：build_clean_ir 有 _CACHE；本测试**不就地 mutate** 它，
        # 变异测试一律用 model_copy(deep=True)，避免污染共享基线。
        self.ir = build_clean_ir(Medium.NOVEL)
        self.tmp = tempfile.mkdtemp()

    def _only_zip(self) -> str:
        zips = [f for f in os.listdir(self.tmp) if f.endswith(".zip")]
        self.assertEqual(len(zips), 1, f"期望恰好一个 zip，实际 {zips}")
        return os.path.join(self.tmp, zips[0])

    def test_pack_contains_expected_members(self) -> None:
        path = build_evidence_pack(self.ir, self.tmp)
        self.assertTrue(os.path.exists(path), "zip 未生成")
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        for required in ("ir.json", "decisions.json", "MANIFEST.json"):
            self.assertIn(required, names, f"缺失成员 {required}")
        # process_report 允许 .md 或 .txt（降级形态）
        has_report = "process_report.md" in names or "process_report.txt" in names
        self.assertTrue(has_report, "缺失 process_report.md/.txt")

    def test_ir_roundtrip_replayable(self) -> None:
        """打包后的 ir.json 重放分数 == 原始 ir 分数（可重放性）。"""
        build_evidence_pack(self.ir, self.tmp)
        with zipfile.ZipFile(self._only_zip()) as zf:
            ir_data = json.loads(zf.read("ir.json").decode("utf-8"))
            manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8"))

        loaded = NarrativeIR.model_validate(ir_data)
        self.assertEqual(
            run_all(loaded).score(),
            run_all(self.ir).score(),
            "重放分数与原始分数不一致 —— 证据包不可重放",
        )
        # 文件名后缀必须与 MANIFEST 指纹一致（声明与内容对齐）
        self.assertTrue(
            os.path.basename(self._only_zip()).endswith(f"_{manifest['fingerprint']}.zip"),
            "zip 文件名指纹与 MANIFEST 不一致",
        )

    def test_decisions_json_empty_when_no_proposals(self) -> None:
        self.assertEqual(self.ir.proposals, [])
        build_evidence_pack(self.ir, self.tmp)
        with zipfile.ZipFile(self._only_zip()) as zf:
            decisions = json.loads(zf.read("decisions.json").decode("utf-8"))
        self.assertEqual(decisions, {"proposals": []})

    def test_decisions_json_captures_proposals(self) -> None:
        """若 IR 含已裁决提案，decisions.json 必须逐条记录（主张证据）。"""
        ir = self.ir.model_copy(deep=True)
        from loom.ir.proposal import Diff, DiffStatus

        ir.proposals = [
            Diff(
                id="d1",
                target_card="s1",
                field="goal",
                before="旧目标",
                after="新目标",
                rationale="更贴合主题",
                source_card="c1",
                status=DiffStatus.REJECTED,
                decided_by="human",
            )
        ]
        out = tempfile.mkdtemp()
        build_evidence_pack(ir, out)
        zp = os.path.join(out, [f for f in os.listdir(out) if f.endswith(".zip")][0])
        with zipfile.ZipFile(zp) as zf:
            decisions = json.loads(zf.read("decisions.json").decode("utf-8"))
        self.assertEqual(len(decisions["proposals"]), 1)
        self.assertEqual(decisions["proposals"][0]["status"], "rejected")

    def test_mutation_changes_fingerprint(self) -> None:
        """改动场景正文必须改变指纹 —— 指纹与内容绑定（可复现 / 不可伪造）。"""
        base_path = build_evidence_pack(self.ir, self.tmp)
        with zipfile.ZipFile(base_path) as zf:
            base_fp = json.loads(zf.read("MANIFEST.json").decode("utf-8"))["fingerprint"]

        mutated = self.ir.model_copy(deep=True)
        s0 = mutated.scenes[0]
        s0.prose = (s0.prose or "") + " 这是一处人工修订的附加正文，用于触发指纹变化。"

        out2 = tempfile.mkdtemp()
        new_path = build_evidence_pack(mutated, out2)
        with zipfile.ZipFile(new_path) as zf:
            new_fp = json.loads(zf.read("MANIFEST.json").decode("utf-8"))["fingerprint"]

        self.assertNotEqual(base_fp, new_fp, "改动内容后指纹未变 —— 指纹未绑定内容")

        # 变异后的包同样可重放：分数是确定性的
        with zipfile.ZipFile(new_path) as zf:
            loaded = NarrativeIR.model_validate(
                json.loads(zf.read("ir.json").decode("utf-8"))
            )
        self.assertEqual(run_all(loaded).score(), run_all(mutated).score())


if __name__ == "__main__":
    unittest.main()
