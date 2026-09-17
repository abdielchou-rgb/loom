#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Web 默认首屏（P0 · 默认路径修复）单元测试。

守三条设计约束，每条都可证伪：

  A. **默认不要求粘贴 JSON**：首屏必须是一句话输入框 + 「载入已有 IR 文件」
     两个低门槛入口；不能把「贴一段 ir.json」当主路径（那是 Apple 级审计
     点名的 friction）。
  B. **离线自包含**：首屏 HTML 不引 CDN / 外链 / 外部脚本，断网可看（铁律 6）。
  C. **不出裸 traceback**：任何未预期异常都要渲染成友好页（P-21）。

运行：`.venv/Scripts/python.exe tests/test_web_default.py`
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loom import web  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if not cond else ""))


# ── A. 默认不要求粘贴 JSON ────────────────────────────────────────


def test_default_exposed() -> None:
    """模块必须暴露一个稳定的默认/索引渲染入口（铁律：不随内部重构漂移）。"""
    fn = getattr(web, "render_index", None)
    check("暴露 render_index 索引入口", callable(fn))
    check("build_form_page 仍是默认首屏", callable(getattr(web, "build_form_page", None)))


def test_default_no_json_paste() -> None:
    """首屏（无 JSON body）必须是一句话引导，绝不能把『贴 JSON』当主指令。"""
    html = web.render_index()
    low = html.lower()
    friendly = ("一句话" in html) or ("想法" in html)
    check("首屏含『一句话 / 想法』友好提示", friendly)
    check("首屏不要求粘贴 JSON（无『粘贴』）", "粘贴" not in html)
    check("首屏不要求 paste（无 'paste'）", "paste" not in low)
    # 两个低门槛入口都要在：
    check("首屏有一句话输入框", "idea" in html and "textarea" in low)
    check("首屏有『载入已有 IR 文件』入口", "载入已有 IR 文件" in html)


# ── B. 离线自包含 ────────────────────────────────────────────────


def test_default_self_contained() -> None:
    """发给别人的首屏不能依赖外网（铁律 6）。"""
    html = web.render_index().lower()
    check("首屏无外链 http(s)", "http://" not in html and "https://" not in html)
    check("首屏无 cdn 引用", "cdn" not in html)
    check("首屏无外部 <script src>", "src='http" not in html and "src=\"http" not in html)
    check("首屏含内联 CSS", "<style>" in html)


# ── C. 异常安全（P-21）─────────────────────────────────────────────


def _make_handler_instance():
    """用 unittest.mock 造一个不绑定 socket 的 handler 实例，捕获响应体。"""
    Handler = web._make_handler(lambda **k: None, Path("out"))
    h = Handler.__new__(Handler)  # 不跑 __init__（那会真的去 accept 连接）
    h._headers_buffer = []
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO()
    h.headers = mock.MagicMock()
    h.headers.get.return_value = "0"
    h.protocol_version = "HTTP/1.0"
    # __init__ 才会设的字段，send_response 内部会用到，这里补上：
    h.requestline = ""
    h.request_version = "HTTP/1.0"
    h.client_address = ("127.0.0.1", 0)
    return h


def test_friendly_error_on_unexpected_exception() -> None:
    """未预期异常必须变成友好页，绝不能把 Python traceback 甩给非技术用户。"""
    h = _make_handler_instance()
    boom = RuntimeError("something internal blew up")
    h._send_friendly_error(boom)
    body = h.wfile.getvalue().decode("utf-8", "replace")
    check("友好页是 HTML", "<!doctype html>" in body.lower())
    check("友好页说明出错了（不崩）", "出了点问题" in body)
    check("友好页不含裸 traceback", "Traceback (most recent call last)" not in body)
    check("友好页给出可操作的下一步", "回到首页" in body)


def test_get_handler_catches_exception() -> None:
    """do_GET 内部抛异常时，整条请求仍落在友好页（验证 wrapper 真的兜住了）。"""
    h = _make_handler_instance()
    h.path = "/"
    with mock.patch.object(web, "build_form_page", side_effect=ValueError("kaboom")):
        try:
            h.do_GET()
        except Exception as exc:  # 若 wrapper 失效，这里会收到裸异常
            check("do_GET 兜住异常（无裸 traceback）", False, f"未被捕获：{exc!r}")
            return
    body = h.wfile.getvalue().decode("utf-8", "replace")
    check("do_GET 异常后仍是友好页", "出了点问题" in body)
    check("do_GET 异常后无裸 traceback", "Traceback (most recent call last)" not in body)


def test_load_route_renders_report() -> None:
    """POST /load 收到一份合法 IR 文本，应渲染出结构体检报告页（不跑生成）。"""
    from tests.fixtures import clean_copy
    from loom.ir.enums import Medium
    from loom.ir.models import NarrativeIR

    ir_json = clean_copy(Medium.NOVEL).to_json()
    h = _make_handler_instance()
    h.path = "/load"
    h.rfile = io.BytesIO(
        ("ir=" + __import__("urllib.parse").parse.quote(ir_json)).encode("utf-8")
    )
    h.headers.get.return_value = str(len(ir_json) + 3)

    # 复用 handler 的表单解析：直接驱动内部方法，喂入已解析的 gv。
    captured = {}

    def fake_gv(name, default=""):
        captured.setdefault("called", True)
        return ir_json if name == "ir" else default

    h._do_load(fake_gv)
    body = h.wfile.getvalue().decode("utf-8", "replace")
    check("/load 产出 HTML 报告", "<!doctype html>" in body.lower())
    check("/load 报告含结构健康分", "结构健康分" in body)
    check("/load 报告带回首链接", "回到 Loom 首页" in body)


def test_load_route_rejects_bad_ir() -> None:
    """POST /load 收到坏 JSON，应回到友好表单，而不是裸 traceback。"""
    h = _make_handler_instance()
    h.path = "/load"

    def fake_gv(name, default=""):
        return "这不是合法 JSON {{{" if name == "ir" else default

    h._do_load(fake_gv)
    body = h.wfile.getvalue().decode("utf-8", "replace")
    check("/load 坏 IR 回到友好表单", "读不出来" in body)
    check("/load 坏 IR 无裸 traceback", "Traceback (most recent call last)" not in body)


def main() -> int:
    print("=" * 64)
    print("Web 默认首屏（P0 · 默认路径修复）单元测试")
    print("=" * 64)
    for fn in (
        test_default_exposed,
        test_default_no_json_paste,
        test_default_self_contained,
        test_friendly_error_on_unexpected_exception,
        test_get_handler_catches_exception,
        test_load_route_renders_report,
        test_load_route_rejects_bad_ir,
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
