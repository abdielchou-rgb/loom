#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对 awareness.py 做变异测试：把实现改坏，确认 tests/test_awareness.py 变红。

铁律 29：必须用 try/finally 还原。一次异常让被改坏的文件留在磁盘上，
下一次读到的「原始内容」已经是变异版本，后续断言全绿但都在测坏代码。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "keel" / "provenance" / "awareness.py"
TEST = ROOT / "tests" / "test_awareness.py"

MUTATIONS: list[tuple[str, str, str]] = [
    (
        "pending 也算进 decided",
        'out["decided"] = out["accepted"] + out["rejected"] + out["conflicted"]',
        'out["decided"] = out["accepted"] + out["rejected"] + out["conflicted"] + out["pending"]',
    ),
    (
        "scenes_touched 改数 AI 直出",
        "{ChunkOrigin.HUMAN, ChunkOrigin.AI_ASSISTED, ChunkOrigin.AI_EDITED}",
        "{ChunkOrigin.AI_GENERATED}",
    ),
    (
        "去掉 CHI 2026 说明行",
        '"  ↑ CHI 2026：AI 协同写作中，作者往往**察觉不到** AI 对自己方向的影响，"',
        '"  ↑ 这是一行统计信息。"',
    ),
    (
        "awareness_line 追加评分（把觉察变成可刷指标）",
        'return " · ".join(parts)',
        'return " · ".join(parts) + f" · 判断力 {min(100, c[\'decided\'] * 20)} 分"',
    ),
]


def run_test() -> bool:
    """返回 True 表示测试通过（绿）。"""
    r = subprocess.run(
        [sys.executable, str(TEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode == 0


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    print("基线：", "绿" if run_test() else "红（基线就是红的，先修测试）")
    if not run_test():
        return 1

    all_red = True
    try:
        for name, old, new in MUTATIONS:
            if old not in original:
                print(f"  ⚠ 变异锚点未命中，跳过：{name}")
                all_red = False
                continue
            TARGET.write_text(original.replace(old, new, 1), encoding="utf-8")
            try:
                green = run_test()
            finally:
                TARGET.write_text(original, encoding="utf-8")
            status = "✗ 仍绿（断言是空的！）" if green else "✓ 变红"
            if green:
                all_red = False
            print(f"  {status}  {name}")
    finally:
        TARGET.write_text(original, encoding="utf-8")
        print("已还原 awareness.py")

    print("\n结论：", "全部变红，断言非空" if all_red else "存在空断言，需补测试")
    return 0 if all_red else 1


if __name__ == "__main__":
    raise SystemExit(main())
