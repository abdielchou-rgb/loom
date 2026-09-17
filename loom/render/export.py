"""按作品报告导出 —— 报告即商品（P5）。

核心论点：**报告是 Loom 目前唯一现成的获客载体**（F5：M0–M3 靠分享）。
一份能**双击打开、能发给别人、断网可验**的单文件报告，比 29 个校验器
和 7 个报表项活在终端里值钱得多 —— 可达性是乘数，不是加法。

设计约束（每一条都是硬约束）：

1. **单文件自包含**：不引 CDN、不引外部字体、不引 JS 库、没有任何
   `http(s)` 外链。断网双击可看。本模块**复用** `html.py` 的渲染器
   （`render_html`），不重造 HTML 主体 —— 报告主体与其它渲染器同源、零漂移。
2. **作品指纹（work fingerprint）**：对 IR 的**规范 JSON** 做 SHA-256，
   并**绑定生成参数 params**，使指纹同时锁定「内容」与「生成方式」。
   规范 JSON 排除 `created_at` 等运行时易变字段、键排序，保证可复现、可离线重算。
3. **不宣称做不到的事**：指纹只是内容/参数的确定性摘要，不由它推出任何质量结论；
   报告里明写「离线可验：用本指纹可在本地重算复现」。

── PDF 是次级能力 ────────────────────────────────────────────────────
`to_pdf` 仅在 `weasyprint`（或 `reportlab`）可 import 时才工作；否则**显式报错**
（`RuntimeError`），绝不静默失败，也绝不把它塞进 `requirements.txt`
（否则就违背了「断网可开 / 无网络依赖」这条铁律）。
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import Path

from html import escape

from ..ir.models import NarrativeIR
from .html import render_html

__all__ = ["work_fingerprint", "export_report", "to_pdf"]

#: 返回指纹的字符长度（SHA-256 前 16 位十六进制 = 64 位可选空间中的一段，
#: 足以在单作品内区分不同生成参数，且短到便于人读/复制）。
_FP_LEN = 16

#: 规范序列化时排除的**运行时易变字段**（非内容、非生成参数）。
#: `Provenance.created_at` 默认为 `datetime.now()`，每次构建都会变 —— 它属于
#: 溯源时间戳，不是作品内容，必须排除，否则同一作品每次导出指纹都不同。
_EXCLUDE_VOLATILE = {"provenance": {"__all__": {"created_at": True}}}


def _json_default(o):
    """让 enum / pydantic 模型 / 其它非原生类型也能进规范 JSON。"""
    if isinstance(o, Enum):
        return o.value
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    return str(o)


def _canonical(ir: NarrativeIR, params: dict | None) -> str:
    """IR（规范 JSON，排除易变字段）+ 生成参数 → 稳定、可复现的字符串。"""
    ir_data = ir.model_dump(mode="json", exclude=_EXCLUDE_VOLATILE)
    payload = {"ir": ir_data, "params": params or {}}
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def work_fingerprint(ir: NarrativeIR, params: dict | None = None) -> str:
    """作品指纹：IR 规范 JSON + 生成参数 params 的确定性 SHA-256（取前 16 位）。

    确定性保证：
      * IR 用 `model_dump(mode="json")` 序列化（enum→值、datetime→ISO、键稳定）。
      * 排除 `created_at` 等运行时易变字段，使同一作品多次导出指纹稳定。
      * `sort_keys=True` + 紧凑分隔符 → 与字段插入顺序无关。
      * `params`（如 `{"medium", "scenes", "words"}`）并入哈希，
        使指纹同时绑定「内容」与「生成方式」—— 同 IR 不同参数 → 不同指纹。

    返回前 16 位十六进制（共 64 位可选空间，短且便于人读）。
    """
    canonical = _canonical(ir, params).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:_FP_LEN]


def _assert_no_external(html: str, path: str) -> None:
    """断网可开硬约束：文件内不得出现任何 `http(s)` 外链（svg 的 w3.org 命名空间除外）。

    若某条外链混进来了，直接抛清晰错误而非静默写出一份「断网白屏」的文件。
    """
    for m in re.finditer(r"https?://[^\s\"'<>]+", html):
        url = m.group(0)
        # 仅允许 svg xmlns 这类命名空间声明（不存在外链加载行为）。
        if "www.w3.org" in url:
            continue
        raise RuntimeError(
            f"导出的报告含外部链接 {url!r}，违反「断网可开」约束：{path}"
        )


def _fingerprint_block(ir: NarrativeIR, params: dict | None, fp: str) -> str:
    """内嵌指纹块。复用 html.py 已注入的 `<style>` 中的类名（card/kv/k/note），
    并加一个高亮边框使「这是可离线验证的作品指纹」一目了然。"""
    param_rows = "".join(
        f"<div class='kv'><div class='k'>{escape(str(k))}</div>"
        f"<div class='v'>{escape(str(v))}</div></div>"
        for k, v in (params or {}).items()
    )
    return (
        "<div id='work-fingerprint' style='margin-top:20px;padding:16px 18px;"
        "border:2px solid var(--accent);border-radius:10px;background:#f4f1ec'>"
        "<h2 style='margin-top:0'>作品指纹（Work Fingerprint）</h2>"
        "<div class='grid'>"
        f"<div class='kv' style='grid-column:1/-1'>"
        f"<div class='k'>指纹 SHA-256 / 前 {_FP_LEN} 位</div>"
        f"<div class='v' style='font-family:ui-monospace,SFMono-Regular,Menlo,"
        f"monospace;word-break:break-all'>{escape(fp)}</div></div>"
        f"{param_rows}"
        "</div>"
        "<p class='note' style='margin-bottom:0'>"
        "离线可验：用本指纹可在本地重算复现。指纹 = SHA-256 对 IR 的规范 JSON"
        "（排除 created_at 等运行时字段、键排序）+ 生成参数 params 的稳定哈希。"
        "本文件自包含、无外链，断网双击即可打开验证。</p>"
        "</div>"
    )


def export_report(ir: NarrativeIR, out_path: str, params: dict | None = None) -> str:
    """导出**单文件自包含 HTML** 报告到 `out_path`。

    内容 = (a) `html.py` 的渲染主体（`render_html`，不拷贝、直接调用）+ 
    (b) 内嵌作品指纹块。返回作品指纹字符串。

    文件内**绝对无** `http(s)` 外链 / 外部 `<script src>` / `<link href>`；
    任何外链会触发 `RuntimeError` 而非写出白屏文件。
    """
    # (a) 复用已有渲染器 —— 不重造主体，零漂移
    body = render_html(ir)

    # (b) 计算并内嵌指纹块
    fp = work_fingerprint(ir, params)
    block = _fingerprint_block(ir, params, fp)

    if "</body>" in body:
        html = body.replace("</body>", block + "\n</body>", 1)
    else:
        html = body + block

    _assert_no_external(html, out_path)

    Path(out_path).write_text(html, encoding="utf-8")
    return fp


def to_pdf(html_path: str, pdf_path: str) -> str:
    """HTML → PDF（次级能力）。仅在 weasyprint / reportlab 可 import 时工作。

    否则**显式报错**，绝不静默失败、绝不假装成功。不向 requirements.txt
    添加任何 PDF 依赖（断网可开 / 无网络依赖 是铁律）。
    """
    try:
        from weasyprint import HTML as _WPHTML  # type: ignore
    except ImportError:
        try:
            from reportlab.pdfgen import canvas as _rl_canvas  # type: ignore
        except ImportError:
            raise RuntimeError(
                "PDF 导出需要 weasyprint：pip install weasyprint"
                "（或先用 export_report 导出 HTML）"
            )
        # reportlab 路径：极简降级（仅验证可达性，不保证样式完美）。
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        text = Path(html_path).read_text(encoding="utf-8")
        c = canvas.Canvas(pdf_path, pagesize=A4)
        c.drawString(50, 800, "Loom 报告（由 reportlab 降级导出，样式有限）")
        y = 770
        for line in text.splitlines()[:200]:
            if y < 40:
                c.showPage()
                y = 800
            c.drawString(50, y, line[:120])
            y -= 14
        c.showPage()
        c.save()
        return pdf_path

    _WPHTML(filename=html_path).write_pdf(pdf_path)
    return pdf_path
