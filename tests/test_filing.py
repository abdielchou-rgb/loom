"""备案材料渲染器（`keel/render/filing.py`）单元测试。

覆盖 P5 · 备案材料 A 层 —— 每集 AI 标识清单：

    * 微短剧：每集一个条目，标签正确；
    * 其它媒介：正确跳过（返回 `[]`，不伪造条目）；
    * markdown：含免责声明 + 第34条引用；
    * 一致性：场景数变化 → 清单长度变化（清单忠实于 IR，而非写死）。
"""

import unittest
from pathlib import Path

sys_path_boost = str(Path(__file__).resolve().parent.parent)
import sys

if sys_path_boost not in sys.path:
    sys.path.insert(0, sys_path_boost)

from keel.ir.enums import Medium
from keel.render.filing import build_filing_list, render_filing_csv, render_filing_markdown
from tests.fixtures import build_clean_ir, clean_copy

LABEL = "本集由人工智能辅助生成"
DISCLAIMER = "以主管部门最新口径为准"


class FilingListTest(unittest.TestCase):
    def test_micro_drama_one_entry_per_episode(self):
        ir = build_clean_ir(Medium.MICRO_DRAMA)
        rows = build_filing_list(ir)
        # 每集一个条目
        self.assertEqual(len(rows), len(ir.scenes))
        for row in rows:
            self.assertEqual(row["label"], LABEL)
            self.assertIn("episode", row)
            self.assertIn("note", row)

    def test_novel_skipped_is_not_faked(self):
        # 非微短剧：清单不适用，应跳过（返回 []），绝不编造条目
        ir = build_clean_ir(Medium.NOVEL)
        self.assertEqual(build_filing_list(ir), [])

    def test_markdown_carries_disclaimer_and_citation(self):
        ir = build_clean_ir(Medium.MICRO_DRAMA)
        md = render_filing_markdown(ir)
        self.assertIn("微短剧 AI 生成标识清单（每集）", md)
        self.assertIn(LABEL, md)
        self.assertIn(DISCLAIMER, md)  # 诚实声明：以主管部门口径为准
        self.assertIn("第34条", md)     # 引用广电令16号 第34条

    def test_scene_count_change_reflects_in_list(self):
        # 一致性：清单长度必须随场景数变化，不能写死
        ir = clean_copy(Medium.MICRO_DRAMA)
        before = len(build_filing_list(ir))
        ir.scenes = ir.scenes[:-1]  # 去掉一集
        after = len(build_filing_list(ir))
        self.assertEqual(after, before - 1)
        # 同时验证：换成非微短剧后立即正确跳过（不随场景数伪造）
        ir.medium = Medium.NOVEL
        self.assertEqual(build_filing_list(ir), [])

    def test_csv_has_header_and_one_row_per_episode(self):
        ir = build_clean_ir(Medium.MICRO_DRAMA)
        csv = render_filing_csv(ir)
        self.assertIn("episode,label", csv)
        data_rows = [
            ln for ln in csv.strip().splitlines() if ln and not ln.startswith("episode")
        ]
        self.assertEqual(len(data_rows), len(ir.scenes))


if __name__ == "__main__":
    unittest.main()
