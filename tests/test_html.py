#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HTML 报告渲染器（`loom/render/html.py`）单元测试。

依据：第一性原理 D3 —— **可达性是乘数，不是加法**。
一个到不了用户手里的判断，价值为零。已有 5 个渲染器全是文本格式，
29 个校验器的结论只活在终端里。

本测试守的是**三条设计约束**，每条都能被证伪：

  A. **自包含**：不引 CDN / 外链 / 外部字体 / JS 库 —— 断网双击可看
  B. **不隐瞒覆盖率**：健康分与「有多少项真的跑了」必须同时出现
  C. **觉察可见**：报告里必须有「人类判断痕迹」区块（CHI 2026）

外加一条安全约束：作者可控的文本（前提 / 场景 / 提案理由）必须被转义。

变异测试结果（改实现后本测试必须变红，已逐条实测）：

| 变异 | 结果 |
|---|---|
| CSS 里加一个 CDN `<link>` | 红（test_self_contained） |
| 去掉「评估覆盖」区块 | 红（test_reports_coverage） |
| 去掉「人类判断痕迹」区块 | 红（test_awareness_visible） |
| `escape()` 换成原样输出 | 红（test_escapes_author_text） |

运行：`.venv/Scripts/python.exe tests/test_html.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loom.ir.enums import Medium, Severity
from loom.render.html import render_html
from loom.validators import run_all

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if not cond else ""))


def _mk_ir():
    from tests.fixtures import clean_copy

    return clean_copy(Medium.NOVEL)


# ── A. 自包含 ────────────────────────────────────────────────────


def test_self_contained() -> None:
    """目标是「发给别人」。任何外链都会在某些环境下变成白屏。"""
    html = render_html(_mk_ir())
    low = html.lower()
    check("无外链 http(s)", "http://" not in low and "https://" not in low)
    check("无 cdn 引用", "cdn" not in low)
    check("无 <script>", "<script" not in low)
    check("无外部字体引用", "@import" not in low and "fonts.googleapis" not in low)
    check("内联了 CSS", "<style>" in low)
    check("是完整文档", low.startswith("<!doctype html>"))


# ── B. 不隐瞒覆盖率 ──────────────────────────────────────────────


def test_reports_coverage() -> None:
    """只报健康分不报覆盖率 = 隐瞒「有多少项没测」。"""
    ir = _mk_ir()
    html = render_html(ir, run_all(ir))
    check("含『评估覆盖』区块", "评估覆盖" in html)
    check("含『跳过』计数", "跳过" in html)
    check("含『崩溃』计数", "崩溃" in html)
    check("含覆盖率百分比", "%" in html)


def test_shows_score() -> None:
    ir = _mk_ir()
    rep = run_all(ir)
    html = render_html(ir, rep)
    check("含结构健康分", "结构健康分" in html)
    check("分数数字出现", f">{rep.score()}<" in html, f"score={rep.score()}")


# ── C. 觉察可见 ──────────────────────────────────────────────────


def test_awareness_visible() -> None:
    """CHI 2026：作者察觉不到 AI 的影响。报告里必须让他看见自己的判断。"""
    ir = _mk_ir()
    html = render_html(ir)
    check("含『人类判断痕迹』区块", "人类判断痕迹" in html)
    check("说明了来源 CHI 2026", "CHI 2026" in html)
    check("含裁决计数", "已裁决" in html and "待裁决" in html)


# ── 语义分隔：结构分 vs 非结构信号 ───────────────────────────────


def test_advisory_separated() -> None:
    ir = _mk_ir()
    rep = run_all(ir)
    html = render_html(ir, rep)
    check("有『非结构信号』区块", "非结构信号" in html)
    check("明说不计入健康分", "不计入健康分" in html)
    # 必须比的是**章节标题**，不是第一次出现的位置：
    # 「结构健康分」的说明里就提前提到了「非结构信号」，用 index("非结构信号")
    # 会命中那句交叉引用，断言就变成了测文案顺序而不是测分区。
    check("advisory 与结构分区分开放（按章节标题）",
          html.index("<h2>非结构信号") > html.index("<h2>体检明细"),
          f"{html.index('<h2>非结构信号')} vs {html.index('<h2>体检明细')}")


# ── 安全：作者可控文本必须转义 ───────────────────────────────────


def test_escapes_author_text() -> None:
    """IR 里的文本来自作者（前提 / 场景 / 提案理由）。

    报告是要**发给别人**的，未转义的 `<script>` 会变成一个 XSS 载体。
    """
    ir = _mk_ir()
    ir.commitment.premise = "<script>alert(1)</script>前提"
    ir.title = "<img src=x onerror=alert(1)>"
    html = render_html(ir)
    check("前提中的 <script> 被转义", "<script>alert(1)</script>" not in html)
    check("标题中的 <img 被转义", "<img src=x" not in html)
    check("但仍能看到原文（不吞内容）", "前提" in html)


# ── 健壮性 ───────────────────────────────────────────────────────


def test_handles_empty_and_broken() -> None:
    ir = _mk_ir()
    # 崩溃项必须被显示，且明说不扣分
    rep = run_all(ir)
    rep.crashes["fake_validator"] = "模拟崩溃"
    html = render_html(ir, rep)
    check("崩溃项会出现在报告里", "fake_validator" in html or "崩溃" in html)
    check("崩溃明说不扣健康分", "不扣健康分" in html)


def test_no_crash_on_minimal() -> None:
    ir = _mk_ir()
    for s in ir.scenes:
        s.prose = ""
    ir.proposals = []
    try:
        html = render_html(ir)
        check("空正文 + 无提案也能渲染", len(html) > 500, f"len={len(html)}")
    except Exception as exc:
        check("空正文 + 无提案也能渲染", False, f"异常：{exc}")


def main() -> int:
    print("=" * 64)
    print("HTML 报告渲染器单元测试")
    print("=" * 64)
    for fn in (
        test_self_contained,
        test_reports_coverage,
        test_shows_score,
        test_awareness_visible,
        test_advisory_separated,
        test_escapes_author_text,
        test_handles_empty_and_broken,
        test_no_crash_on_minimal,
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
