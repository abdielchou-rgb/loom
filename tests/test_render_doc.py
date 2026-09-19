"""文档渲染器 —— 测试先行。

跑法：
    .venv/Scripts/python.exe tests/test_render_doc.py

零依赖（不用 pytest），与本项目其余部分一致。

── 为什么这个模块值得有测试 ──────────────────────────────

它是个「生成 HTML」的模块，而**生成 HTML 最危险的缺陷是转义**：
漏一次 `html.escape`，文档正文里的 `<script>` 就变成了真的标签。
这在本地看不出任何异常（渲染结果「看起来对」），
但一旦这份 HTML 被分享出去，它就是一条注入路径。

所以下面第 1 组是**安全断言**，不是格式断言：
它是这个模块唯一的「变异后必须变红」的判据 ——
把 `_esc` 去掉，这一组立刻红。

第 2 组覆盖「不该被处理」的情况（代码块里的 `**` 不是粗体），
理由与 CSN 那条一样：**误处理的代价比不处理高**。

── 期望值的来源 ────────────────────────────────────────

来自 CommonMark 的块级规则（代码围栏 / 表格分隔行 / 引用块 / 列表连续性），
不是从实现里抄回来的。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.render_doc import inline, page, render  # noqa: E402


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def eq(self, got, want, label: str) -> None:
        if got == want:
            self.passed += 1
        else:
            self.failed.append(f"{label}\n      期望 {want!r}\n      实际 {got!r}")

    def ok(self, cond: bool, label: str) -> None:
        if cond:
            self.passed += 1
        else:
            self.failed.append(label)

    def group(self, name: str) -> None:
        print(f"\n  {name}")


# ---------------------------------------------------------------------------
# 1. 安全：转义（本模块唯一的「去掉就变红」判据）
# ---------------------------------------------------------------------------


def test_escaping(t: T) -> None:
    t.group("1. 转义 —— 正文里的标签不许变成真标签")

    t.ok(
        "<script>" not in render("<script>alert(1)</script>"),
        "裸 <script> 必须被转义（这是本模块最重要的断言）",
    )
    t.ok(
        "&lt;script&gt;" in render("<script>alert(1)</script>"),
        "<script> 应转义成 &lt;script&gt;",
    )
    t.ok("<img" not in render('<img src=x onerror="alert(1)">'),
         "裸 <img onerror> 必须被转义")

    # 表格单元格、标题、列表项 —— 三个都会经过 inline()，逐个验
    t.ok("<b>" not in render("| <b>x</b> | y |\n|---|---|\n| 1 | 2 |"),
         "表格单元格里的标签必须转义")
    t.ok("<b>" not in render("## <b>标题</b>"), "标题里的标签必须转义")
    t.ok("<b>" not in render("- <b>项</b>"), "列表项里的标签必须转义")

    # 引用块走的是 inline()，且用 <br> 连接 —— 转义不能被 <br> 绕过
    t.ok("<i>" not in render("> <i>x</i>"), "引用块里的标签必须转义")

    # & 必须先于 < > 转义，否则 &lt; 会被二次转义成 &amp;lt;
    t.eq(inline("a & b"), "a &amp; b", "裸 & 应转义为 &amp;")
    t.eq(inline("&lt;"), "&amp;lt;", "已转义的实体不再被二次转义")


# ---------------------------------------------------------------------------
# 2. 「不该被处理」的情况
# ---------------------------------------------------------------------------


def test_no_false_processing(t: T) -> None:
    t.group("2. 代码块内不套用内联标记")

    html = render("```\n**not bold**\n`x`\n```")
    t.ok("<strong>" not in html, "代码块里的 ** 不许变成粗体")
    # 注意：`<pre><code>` 是代码块的**外层包装**，它本来就该有。
    # 这条断言查的是「内层反引号不许再套一层 <code>」，所以数的是**个数**。
    # （第一版写成 `"<code>" not in html` 是错的 —— 报警的是测试，不是实现。）
    t.eq(html.count("<code>"), 1, "代码块只应有外层那一个 <code>")
    t.ok("`x`" in html, "代码块里的反引号必须原样保留")
    t.ok("**not bold**" in html, "代码块内容应原样保留")

    # 星号紧贴的情况：*a* 是斜体，**a** 是粗体，不该互相吞掉
    t.ok("<strong>x</strong>" in inline("**x**"), "**x** -> <strong>")
    t.ok("<em>x</em>" in inline("*x*"), "*x* -> <em>")


# ---------------------------------------------------------------------------
# 3. 块级结构
# ---------------------------------------------------------------------------


def test_blocks(t: T) -> None:
    t.group("3. 块级结构")

    # 表格：分隔行不能变成一行数据
    html = render("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |")
    t.eq(html.count("<tr>"), 3, "表格应有 1 表头行 + 2 数据行")
    t.ok("---" not in html, "分隔行 |---|---| 不许渲染成数据行")

    # 引用块：连续 > 行合成一个 blockquote
    html = render("> 第一行\n> 第二行")
    t.eq(html.count("<blockquote>"), 1, "连续引用行应合成一个 blockquote")
    t.ok("第一行" in html and "第二行" in html, "两行内容都要在")

    # 列表：同类型连续行合成一个列表；不同类型不许混进同一个
    html = render("- a\n- b\n- c")
    t.eq(html.count("<ul>"), 1, "连续 - 应合成一个 <ul>")
    t.eq(html.count("<li>"), 3, "应有 3 个 <li>")

    html = render("- a\n\n1. b")
    t.ok("<ul>" in html and "<ol>" in html, "- 与 1. 应各自成列表")

    # 标题层级
    t.eq(render("# x"), "<h1>x</h1>", "一级标题")
    t.eq(render("### x"), "<h3>x</h3>", "三级标题")

    # 分隔线
    t.ok("<hr>" in render("---"), "--- 应渲染为 <hr>")


# ---------------------------------------------------------------------------
# 4. 不静默丢弃
# ---------------------------------------------------------------------------


def test_nothing_is_dropped(t: T) -> None:
    t.group("4. 不认识的语法当段落，不许丢")

    # 一条不构成任何块级语法的怪行
    weird = "~~~ 这行什么语法都不是 ~~~"
    t.ok(weird in render(weird), "不认识的块级语法必须原样保留为段落")

    # 多行段落合并
    html = render("第一行\n第二行")
    t.eq(html.count("<p>"), 1, "连续非空行应合成一个段落")

    # 空文档不崩
    t.eq(render(""), "", "空输入应产出空字符串")


# ---------------------------------------------------------------------------
# 5. 自包含（交付主张）
# ---------------------------------------------------------------------------


def test_self_contained(t: T) -> None:
    t.group("5. 输出自包含 —— 零外部资源")

    html = page("# 标题\n\n正文", "标题")
    for bad in ('<script', '<link ', 'src="http', "src='http"):
        t.ok(bad not in html, f"输出不许含 {bad}")
    t.ok("<style>" in html, "样式必须内联在 <style> 里")
    t.ok(html.startswith("<!DOCTYPE html>"), "应是完整 HTML 文档")
    t.ok('lang="zh-CN"' in html, "应声明中文语言")


def main() -> int:
    print("文档渲染器 —— 自检")
    t = T()
    test_escaping(t)
    test_no_false_processing(t)
    test_blocks(t)
    test_nothing_is_dropped(t)
    test_self_contained(t)
    print(f"\n  通过 {t.passed} · 失败 {len(t.failed)}")
    if t.failed:
        print("  失败项：")
        for f in t.failed:
            print(f"    ✗ {f}")
        return 1
    print("  全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
