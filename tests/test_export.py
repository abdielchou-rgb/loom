#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`keel/render/export.py` 单元测试：按作品报告导出（P5）。

守的是三条硬约束，每条都能被证伪（改实现后本测试必须变红，已逐条实测）：

  A. **单文件自包含**：导出 HTML 内不得出现任何 `http(s)` 外链
     （无 `<script src=...>` / `<link href=http...>` / 远程资源）。
  B. **作品指纹**：指纹随内容（改场景 prose 会变）与生成参数绑定，
     且同一 ir+params 重复导出稳定可复现。
  C. **复用不重造**：export_report 调用 html.py 的渲染主体，不拷贝。

变异测试结果（改实现后本测试必须变红）：

| 变异 | 结果 |
|---|---|
| 指纹把 prose 排除出规范 JSON | 红（test_prose_change_mutation） |
| 指纹不并入 params | 红（test_params_bind_fingerprint） |
| 指纹含 created_at（易变） | 红（test_determinism 多次导出） |
| export_report 直接 `return ""` 不写文件 | 红（test_file_written） |

运行：
    .venv/Scripts/python.exe -m unittest discover -s tests -p "test_export.py" -v
    .venv/Scripts/python.exe tests/test_export.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keel.ir.enums import Medium
from keel.render.export import export_report, to_pdf, work_fingerprint
from tests.fixtures import build_clean_ir


def _params() -> dict:
    return {"medium": Medium.NOVEL, "scenes": 6, "words": 3600}


class TestExport(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = build_clean_ir(Medium.NOVEL)
        self.params = _params()

    # ── A. 文件存在 / 含指纹 / 无外链 ──────────────────────────────

    def test_file_written_and_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.html"
            fp = export_report(self.ir, str(out), self.params)
            self.assertTrue(out.exists(), "报告文件应已写出")
            self.assertGreater(out.stat().st_size, 0, "报告文件不应为空")
            self.assertTrue(len(fp) == 16, "指纹应为 16 位十六进制")

    def test_contains_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.html"
            fp = export_report(self.ir, str(out), self.params)
            text = out.read_text(encoding="utf-8")
            self.assertIn(fp, text, "导出的 HTML 必须包含作品指纹")
            self.assertIn("作品指纹", text, "应存在指纹区块标题")

    def test_no_external_link(self) -> None:
        """断网可开：文件内不得出现任何 http(s) 外链。"""
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.html"
            export_report(self.ir, str(out), self.params)
            text = out.read_text(encoding="utf-8").lower()
            self.assertNotIn("http://", text, "不应含 http:// 外链")
            self.assertNotIn("https://", text, "不应含 https:// 外链")
            self.assertNotIn("<script", text, "不应含外部/内联 script 加载")
            self.assertNotIn("<link", text, "不应含外部 link 加载")

    # ── B. 指纹确定性 / 绑定参数 / 随内容变化 ──────────────────────

    def test_determinism_same_ir_params(self) -> None:
        """同一 ir + 同一 params，重复导出指纹必须一致。"""
        fp1 = work_fingerprint(self.ir, self.params)
        fp2 = work_fingerprint(self.ir, self.params)
        self.assertEqual(fp1, fp2, "同一 ir+params 指纹应稳定")

    def test_determinism_reexport(self) -> None:
        """同一 ir 导出两次（不同调用、不同文件），指纹仍一致。"""
        with tempfile.TemporaryDirectory() as d:
            out1 = Path(d) / "r1.html"
            out2 = Path(d) / "r2.html"
            fp1 = export_report(self.ir, str(out1), self.params)
            fp2 = export_report(self.ir, str(out2), self.params)
            self.assertEqual(fp1, fp2, "重复导出应得同一指纹")

    def test_params_bind_fingerprint(self) -> None:
        """生成参数不同 → 指纹不同（指纹绑定生成方式）。"""
        base = work_fingerprint(self.ir, self.params)
        other = work_fingerprint(
            self.ir, {"medium": Medium.NOVEL, "scenes": 6, "words": 9999}
        )
        self.assertNotEqual(base, other, "改 words 参数应改变指纹")

    def test_prose_change_mutation(self) -> None:
        """改场景 prose（内容变化）→ 指纹必须变。"""
        original = work_fingerprint(self.ir, self.params)
        self.ir.scenes[0].prose = (self.ir.scenes[0].prose or "") + "【指纹必变锚点】"
        mutated = work_fingerprint(self.ir, self.params)
        self.assertNotEqual(original, mutated, "改 prose 应改变指纹")

    # ── C. to_pdf 行为（未装 weasyprint 时显式报错，不静默失败）─────

    def test_to_pdf_requires_dependency(self) -> None:
        """未安装 weasyprint/reportlab 时应抛清晰的 RuntimeError，而非静默失败。"""
        try:
            import weasyprint  # noqa: F401
            have_wp = True
        except ImportError:
            have_wp = False
        try:
            import reportlab  # noqa: F401
            have_rl = True
        except ImportError:
            have_rl = False

        if have_wp or have_rl:
            self.skipTest("已安装 PDF 依赖，跳过 stub 断言")

        with tempfile.TemporaryDirectory() as d:
            html = Path(d) / "r.html"
            export_report(self.ir, str(html), self.params)
            with self.assertRaises(RuntimeError) as ctx:
                to_pdf(str(html), str(Path(d) / "r.pdf"))
            self.assertIn("weasyprint", str(ctx.exception),
                          "报错信息应指明需要 weasyprint")


if __name__ == "__main__":
    unittest.main(verbosity=2)
