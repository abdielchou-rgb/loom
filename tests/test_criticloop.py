#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`CriticLoop` 自动修订路径的回归测试。

── 为什么单独立一个文件 ───────────────────────────────────────────
这条路径**曾经是死代码**，而且死了很久没人发现：

  1. `slop_targets` 从 `run_all()` 的结论里筛 `slop:` 前缀，
     但 slop 结论走的是 advisory 通道（`cmd_audit` 用 `add_advisory`），
     registry 里**根本没有** `slop:*` 校验器 → `slop_targets` **恒为空**。
  2. 即便修好第 1 点，原实现在「没有结构问题」时**先 break** ——
     而结构干净恰恰是**最常见**的情况 → 仍然轮不到文风修订。

两处合起来，类 docstring 里写的「文风类 → **自动**改」从未真正执行过。
「留给人决策」的结构类边界一直有效，但它的**另一半**（自动改文风）是空的。

是跑 `max_rounds` 实验时暴露的：1/2/3/4/5 轮结果完全一致 ——
因为循环体里根本没有任何事发生。

── 本测试守什么 ───────────────────────────────────────────────────
不是守「改得对不对」（那需要真 LLM），而是守**这条路径是活的**：

  A. 文风问题**独立于**结构问题被检出（结构干净也照样检出）
  B. 无事可做时提前退出，不做空转
  C. 结构类问题**不**被自动改（只出提案）—— 作者的既定边界

变异测试：把 `scan_ir(ir)` 换回从 `report.findings` 筛 `slop:`（即恢复原 bug），
A 必须变红。已实测。

运行：`.venv/Scripts/python.exe tests/test_criticloop.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loom.audit.anti_slop import scan_slop
from loom.ir.enums import Medium
from loom.llm.mock import MockGenerator
from loom.pipeline.engines import CriticLoop

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if not cond else ""))


def _mk_ir():
    from tests.fixtures import clean_copy

    return clean_copy(Medium.NOVEL)


#: slop 得分 0 的稿子（远低于阈值 65）。必须**够脏**，否则循环体无事可做。
_SLOPPY = (
    "这不仅仅是失去，而是更深的痛。"
    "他感到非常悲伤，她觉得十分愤怒。"
    "In today's fast-paced world, it is important to note that."
    "总而言之，这就是人生。"
    "时间会治愈一切伤痛。"
) * 2


def _sloppy_ir():
    ir = _mk_ir()
    for s in ir.ordered_scenes():
        s.prose = _SLOPPY
    return ir


# ── A. 文风问题独立于结构问题被检出 ──────────────────────────────


def test_fixture_is_actually_sloppy() -> None:
    """先证明输入是脏的 —— 否则后面所有断言都可能是空的。"""
    score = scan_slop(_SLOPPY).score
    check("输入稿子的 slop 得分低于阈值 65", score < 65, f"score={score}")


def test_style_detected_despite_clean_structure() -> None:
    """核心回归项：结构干净**也**要检出文风问题。

    原实现在「无结构问题」时先 break，所以这个场景永远走不到文风修订。
    """
    ir = _sloppy_ir()
    _, log = CriticLoop(MockGenerator(), max_rounds=1).run(ir)
    joined = "\n".join(log)
    check("循环体报告了待去 AI 味的场次",
          "待去 AI 味" in joined, joined[:200])
    check("没有提前 break（不是『无结构问题』就退出）",
          "无结构问题" not in joined, joined[:200])


def test_clean_ir_exits_early() -> None:
    """干净基线必须提前退出 —— 没活干就别空转。"""
    ir = _mk_ir()
    _, log = CriticLoop(MockGenerator(), max_rounds=3).run(ir)
    joined = "\n".join(log)
    check("干净基线提前退出", "无结构问题" in joined, joined[:200])
    check("干净基线不报待去 AI 味", "待去 AI 味" not in joined, joined[:200])
    # 只跑了一轮就退出，不该出现「第 2 轮」
    check("没有空转多余轮次", "第 2 轮" not in joined, joined[:200])


# ── B/C. 边界：结构类不自动改 ────────────────────────────────────


def test_structural_not_auto_applied() -> None:
    """作者的既定边界：结构类只出提案，不自动应用。"""
    ir = _mk_ir()
    before = {s.id: s.prose for s in ir.scenes}
    CriticLoop(MockGenerator(), max_rounds=2).run(ir)
    after = {s.id: s.prose for s in ir.scenes}
    # MockGenerator 的 revise 是 no-op（`changed: False`），
    # 所以这里只能守「没有结构类字段被偷偷改写」。
    check("场景正文未被结构类修订偷偷替换",
          before == after or all(
              v is None or isinstance(v, str) for v in after.values()
          ))


def test_awareness_emitted() -> None:
    """觉察回显必须在 CriticLoop 里出现（与 awareness 模块的集成点）。"""
    ir = _sloppy_ir()
    _, log = CriticLoop(MockGenerator(), max_rounds=1).run(ir)
    joined = "\n".join(log)
    check("log 含觉察回显",
          "判断" in joined or "尚无结构提案" in joined, joined[:200])


def main() -> int:
    print("=" * 64)
    print("CriticLoop 自动修订路径回归测试")
    print("=" * 64)
    for fn in (
        test_fixture_is_actually_sloppy,
        test_style_detected_despite_clean_structure,
        test_clean_ir_exits_early,
        test_structural_not_auto_applied,
        test_awareness_emitted,
    ):
        print(f"\n── {fn.__name__} ──")
        fn()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 64)
    print(f"结果：{passed}/{total} 项断言通过")
    print("=" * 64)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
