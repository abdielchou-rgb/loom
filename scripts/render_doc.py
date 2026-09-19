"""把项目里的 Markdown 设计文档渲染成**自包含** HTML。

## 为什么需要它

项目的交付主张之一是「报告自包含、断网可开」，但**文档本身**此前只有 `.md` ——
要发给别人看，对方得先装一个 Markdown 阅读器。这跟「第一分钟路径」是同一个病：
**内容对了，但送不到人手上。**

一个自包含 HTML 是同一份内容的另一个**视图**。这与
「IR 是本体，文本只是视图」是同构的，所以它属于 `scripts/`（文档工具），
不该进 `keel/render/`（那六个是**叙事**渲染器，管的是故事，不是文档）。

## 约束（与项目其余部分一致）

* **零依赖** —— 不用 `markdown` 库。装了它就得处理版本漂移与 HTML 白名单。
* **输出零外链、零外部脚本** —— 断网可开。样式全部内联在 `<style>` 里。
* **不猜** —— 只支持本文档体系实际用到的语法；遇到不认识的块级语法，
  当作普通段落输出，**绝不静默丢弃**（丢一段话比渲染错更危险）。

## 用法

    python scripts/render_doc.py 交付方案_最终.md -o 交付方案_最终.html
    python scripts/render_doc.py README.md --title "龙骨 Keel"
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

#: 内联语法。**顺序有讲究**：先转义，再套标记。
#: 反引号先于粗体 —— 否则 `` `**x**` `` 里的星号会被当成粗体。
_INLINE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r'<a href="\2">\1</a>'),
)

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ULIST = re.compile(r"^\s*[-*]\s+(.*)$")
_OLIST = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|[\s:|-]+\|$")
_FENCE = re.compile(r"^```(\w*)\s*$")
_HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")

_CSS = """
:root { --ink:#1a1a1a; --dim:#5c6370; --line:#e3e6ea; --bg:#ffffff;
        --panel:#f7f8fa; --accent:#1f6feb; --warn:#b45309; }
* { box-sizing: border-box; }
body { margin:0; padding:48px 24px 96px; background:var(--bg); color:var(--ink);
       font:16px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif; }
main { max-width: 860px; margin: 0 auto; }
h1,h2,h3,h4 { line-height:1.3; font-weight:650; margin:2em 0 .6em; }
h1 { font-size:1.9em; margin-top:0; padding-bottom:.4em; border-bottom:2px solid var(--line); }
h2 { font-size:1.35em; padding-bottom:.3em; border-bottom:1px solid var(--line); }
h3 { font-size:1.12em; }
h4 { font-size:1em; color:var(--dim); }
p { margin: .8em 0; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
code { background:var(--panel); border:1px solid var(--line); border-radius:4px;
       padding:.1em .35em; font-size:.88em;
       font-family:"Cascadia Mono",Consolas,"Courier New",monospace; }
pre { background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:14px 16px; overflow-x:auto; }
pre code { background:none; border:none; padding:0; font-size:.86em; line-height:1.6; }
blockquote { margin:1.1em 0; padding:.5em 0 .5em 16px; border-left:3px solid var(--accent);
             background:var(--panel); color:#333; border-radius:0 6px 6px 0; }
blockquote p { margin:.35em 0; }
table { border-collapse:collapse; width:100%; margin:1.2em 0; font-size:.94em; }
th,td { border:1px solid var(--line); padding:8px 12px; text-align:left; vertical-align:top; }
th { background:var(--panel); font-weight:650; }
tr:nth-child(even) td { background:#fbfcfd; }
ul,ol { padding-left:1.5em; margin:.8em 0; }
li { margin:.3em 0; }
hr { border:none; border-top:1px solid var(--line); margin:2.4em 0; }
footer { max-width:860px; margin:64px auto 0; padding-top:16px; border-top:1px solid var(--line);
         color:var(--dim); font-size:.85em; }
"""


def _esc(text: str) -> str:
    """HTML 转义。**必须先做**，否则正文里的 `<script>` 会变成真的标签。"""
    return html.escape(text, quote=False)


def inline(text: str) -> str:
    """转义后套用内联标记。"""
    out = _esc(text)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def render(md: str) -> str:
    """Markdown -> HTML 片段（不含 <html>/<body> 外壳）。"""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # --- 围栏代码块 -------------------------------------------------
        fence = _FENCE.match(line)
        if fence:
            lang = fence.group(1)
            i += 1
            buf: list[str] = []
            while i < n and not _FENCE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过收尾围栏
            cls = f' class="lang-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{_esc(chr(10).join(buf))}</code></pre>")
            continue

        # --- 表格 -------------------------------------------------------
        if line.lstrip().startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1].strip()):
            head = _cells(line)
            i += 2
            body: list[list[str]] = []
            while i < n and lines[i].lstrip().startswith("|"):
                body.append(_cells(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            rows = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                for r in body
            )
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>")
            continue

        # --- 标题 -------------------------------------------------------
        heading = _HEADING.match(line)
        if heading:
            lvl = len(heading.group(1))
            out.append(f"<h{lvl}>{inline(heading.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        # --- 分隔线 -----------------------------------------------------
        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        # --- 引用块（连续多行合并为一个）---------------------------------
        if line.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            inner = "<br>".join(inline(b) for b in buf if b)
            out.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue

        # --- 列表（同类型连续行合成一个列表）-----------------------------
        if _ULIST.match(line) or _OLIST.match(line):
            ordered = bool(_OLIST.match(line))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < n:
                m = _OLIST.match(lines[i]) if ordered else _ULIST.match(lines[i])
                if not m:
                    break
                items.append(inline(m.group(2) if ordered else m.group(1)))
                i += 1
            out.append(
                f"<{tag}>" + "".join(f"<li>{it}</li>" for it in items) + f"</{tag}>"
            )
            continue

        # --- 空行 -------------------------------------------------------
        if not line.strip():
            i += 1
            continue

        # --- 段落（连续非空行合并）---------------------------------------
        buf = []
        while i < n and lines[i].strip() and not (
            _HEADING.match(lines[i])
            or _FENCE.match(lines[i])
            or _HR.match(lines[i])
            or lines[i].startswith(">")
            or _ULIST.match(lines[i])
            or _OLIST.match(lines[i])
            or lines[i].lstrip().startswith("|")
        ):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{'<br>'.join(inline(b) for b in buf)}</p>")

    return "\n".join(out)


def page(md: str, title: str) -> str:
    """包成完整、自包含的单文件 HTML。"""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f"<main>\n{render(md)}\n</main>\n"
        f'<footer>由 scripts/render_doc.py 从 Markdown 渲染 · 自包含（零外链、零外部脚本）· '
        f"断网可开</footer>\n</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="render_doc", description="Markdown -> 自包含 HTML")
    ap.add_argument("src", help="输入 .md")
    ap.add_argument("-o", "--out", help="输出 .html（默认与输入同目录同名）")
    ap.add_argument("--title", help="页面标题（默认取首个一级标题）")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_file():
        print(f"找不到文件：{src}", file=sys.stderr)
        return 1
    md = src.read_text(encoding="utf-8")

    title = args.title
    if not title:
        first = next((ln for ln in md.splitlines() if ln.startswith("# ")), "")
        title = first.lstrip("# ").strip() or src.stem

    out = Path(args.out) if args.out else src.with_suffix(".html")
    out.write_text(page(md, title), encoding="utf-8")
    print(f"已写入 {out}（{out.stat().st_size:,} 字节 · 自包含）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
