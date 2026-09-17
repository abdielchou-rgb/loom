"""Loom 本地网页界面（零依赖）。

把「普通人也能操作 Loom」做成现实：一个本地 `http.server`，首屏只有一张
表单（一句话想法 + 几个选择），点「生成」即跑与 CLI `write` **完全相同**的
流水线，产物汇成 `loom.html` 枢纽，直接在浏览器里打开。

设计约束（守铁律 6）：
  * 只用 stdlib —— `http.server` / `urllib.parse` / `html`，无任何第三方包。
  * 页面 HTML 内联、内联 CSS、内联 JS，**无 CDN、无外部字体、无外部脚本**。
  * 服务只绑定 `127.0.0.1`（本地回环）—— 数据不出本机，也不会暴露到局域网。

架构原则：**UI 只是视图**。本模块不自己拼流水线，只把表单参数原样交给
调用方传入的 `writer` 可调用对象（CLI 那边就是 `write_story`），
保证网页路径与命令行路径走的是同一份生成逻辑，不会漂移。
"""

from __future__ import annotations

import html
import http.server
import json
import os
import re
import urllib.parse
import webbrowser
from pathlib import Path

from .ir.enums import ArcShape, Medium
from .ir.templates import list_templates
from .llm.workbuddy_provider import (
    ANSWERS_NAME,
    PARAMS_NAME,
    PendingGeneration,
    WorkBuddyAnswerError,
    queue_dir_for,
)

_TITLE = "Loom · 把一句话变成可检验的故事"

#: 给普通人看的中文标签；option 的 value 仍用枚举值，交给 writer 时无需转换。
_MEDIUM_LABELS: dict[str, str] = {
    "novel": "小说（通用）",
    "web_novel": "网文",
    "screenplay": "影视剧本",
    "micro_drama": "微短剧",
    "interactive_fiction": "互动小说",
    "visual_novel": "视觉小说",
    "comic": "漫画",
    "murder_mystery": "剧本杀",
}
#: 驱动方式。`workbuddy` 不是模型名，是一种**驱动方式**：
#: Loom 不发请求，它发问题 —— 提示词落成待填文件，填完再跑。
#: 放在页面一级而不是藏在命令行里，是因为「没有 key 就用不了」这个印象
#: 本身就是错的，而纠正它的成本只是一个下拉框。
_GENERATOR_CHOICES: tuple[tuple[str, str], ...] = (
    ("workbuddy", "WorkBuddy 驱动（无需 key，产出真内容）"),
    ("mock", "离线参考实现（无需 key，形态对、内容假）"),
    ("model", "真模型（需填下面的模型名与 API key）"),
)

_ARC_LABELS: dict[str, str] = {
    "rags_to_riches": "白手起家（一路向上）",
    "tragedy": "悲剧（一路向下）",
    "man_in_a_hole": "坑中人（先跌后起）",
    "icarus": "伊卡洛斯（先升后坠）",
    "cinderella": "灰姑娘（先抑后扬）",
    "oedipus": "俄狄浦斯（先荣后灭）",
}

#: 首屏示例想法（点击即填入，降低「不知道写什么」的门槛）。
_EXAMPLES: list[str] = [
    "一个替人收尸的刀客，发现自己要收的那具尸体是十年前的自己",
    "外卖员发现每单备注都是同一个人写的遗言",
    "退休教师收到三十年前学生寄来的、还没写完的悔过书",
]

# 表单输入的安全边界：本地服务也接受用户输入，必须夹住，避免生成失控。
_SCENES_RANGE = (1, 30, 5)
_WORDS_RANGE = (50, 5000, 800)

#: 端口自动退让次数。默认 8000 常被别的程序占着（本机实测就占着），
#: 而「起不来」对一个非技术用户等于「这软件坏了」。所以默认往后找空位，
#: 让它自己跑起来，而不是甩一句报错让人去猜。
_PORT_TRIES = 20

_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _clamp_int(raw: str | None, lo: int, hi: int, default: int) -> int:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def build_form_page(
    *,
    values: dict[str, str] | None = None,
    error: str = "",
    preview: bool = False,
) -> str:
    """生成首屏表单 HTML（零依赖、内联）。

    `values` 用于出错后回填，`error` 为非空时显示红色提示条。

    `preview=True` 是**诚实开关**：这张页拿去当「静态预览/截图」时，它背后
    并没有服务，`action="/"` 的 POST 必然打空。若不加提示，用户会以为
    「网页坏了」——实际是「这张图不是真在跑的东西」。预览态明确告知并禁用按钮。
    """
    v = values or {}
    idea = html.escape(v.get("idea", ""), quote=True)
    medium = v.get("medium", "novel")
    arc = v.get("arc", "man_in_a_hole")
    template = v.get("template", "save_the_cat")
    scenes = v.get("scenes", str(_SCENES_RANGE[2]))
    words = v.get("words", str(_WORDS_RANGE[2]))
    model = html.escape(v.get("model", ""), quote=True)
    force_prose = "checked" if v.get("force_prose") else ""
    generator = v.get("generator", "mock")
    generator_opts = "\n".join(
        f'      <option value="{g[0]}"'
        f'{" selected" if g[0] == generator else ""}>{g[1]}</option>'
        for g in _GENERATOR_CHOICES
    )

    medium_opts = "\n".join(
        f'      <option value="{m.value}"'
        f'{" selected" if m.value == medium else ""}>'
        f"{_MEDIUM_LABELS.get(m.value, m.value)}</option>"
        for m in Medium
    )
    arc_opts = "\n".join(
        f'      <option value="{a.value}"'
        f'{" selected" if a.value == arc else ""}>'
        f"{_ARC_LABELS.get(a.value, a.value)}</option>"
        for a in ArcShape
    )
    template_opts = "\n".join(
        f'      <option value="{t.id}"'
        f'{" selected" if t.id == template else ""}>'
        f"{html.escape(t.name, quote=True)}</option>"
        for t in list_templates()
    )
    example_chips = "".join(
        f'<button type="button" class="chip" '
        f"onclick=\"document.getElementById('idea').value="
        f"{html.escape(repr(e), quote=True)}\">"
        f"{html.escape(e, quote=True)}</button>"
        for e in _EXAMPLES
    )
    err_banner = (
        f'<div class="err">⚠ {html.escape(error, quote=True)}</div>' if error else ""
    )
    preview_notice = (
        "<div class='notice'>这是<strong>预览 / 截图</strong>，背后没有服务在跑，"
        "所以下面的按钮<strong>不会真的生成</strong>。<br>"
        "要真正使用：在终端运行 <code>loom web</code>"
        "（或 <code>.venv/Scripts/python.exe -m loom.cli web</code>），"
        "再打开它给出的地址。</div>"
        if preview else ""
    )
    go_cls = "go disabled" if preview else "go"
    go_dis = " disabled" if preview else ""
    go_text = "预览模式 · 请在终端启动 loom web" if preview else "生成并体检"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_TITLE}</title>
<style>
  :root {{
    --bg:#f5f5f7; --ink:#1d1d1f; --mut:#6e6e73; --line:#d2d2d7;
    --acc:#0071e3; --acc-h:#0077ed; --err:#d70015;
  }}
  * {{ box-sizing:border-box; }}
  html, body {{ height:100%; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    display:flex; align-items:center; justify-content:center; padding:28px 20px; }}
  .wrap {{ width:100%; max-width:460px; }}
  .brand {{ font-size:13px; color:var(--mut); letter-spacing:.6px; text-align:center; margin:0 0 22px; }}
  h1 {{ font-size:26px; line-height:1.3; font-weight:600; letter-spacing:-.3px;
    margin:0 0 10px; text-align:center; }}
  .sub {{ font-size:14px; color:var(--mut); margin:0 0 30px; text-align:center; line-height:1.65; }}
  textarea {{ width:100%; min-height:92px; resize:vertical; font:inherit; color:var(--ink);
    background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 16px;
    outline:none; transition:border-color .15s, box-shadow .15s; }}
  textarea:focus {{ border-color:var(--acc); box-shadow:0 0 0 4px rgba(0,113,227,.14); }}
  textarea::placeholder {{ color:#a1a1a6; }}
  .examples {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:center; margin:14px 0 26px; }}
  .chip {{ background:transparent; color:var(--mut); border:1px solid var(--line);
    border-radius:980px; padding:6px 14px; font:13px/1 inherit; cursor:pointer; transition:.15s; }}
  .chip:hover {{ color:var(--ink); border-color:var(--ink); }}
  .go {{ width:100%; background:var(--acc); color:#fff; border:0; border-radius:980px;
    padding:15px; font-size:17px; font-weight:500; cursor:pointer; transition:background .15s; }}
  .go:hover {{ background:var(--acc-h); }}
  .more {{ margin-top:16px; text-align:center; }}
  .more > summary {{ list-style:none; cursor:pointer; color:var(--acc); font-size:14px;
    display:inline-block; padding:6px 4px; }}
  .more > summary::-webkit-details-marker {{ display:none; }}
  .more[open] > summary {{ color:var(--mut); }}
  .opts {{ margin-top:18px; padding-top:20px; border-top:1px solid var(--line); }}
  .opts label {{ display:block; font-size:13px; color:var(--mut); margin:16px 0 6px; }}
  .opts label:first-child {{ margin-top:0; }}
  .opts select, .opts input[type=text] {{ width:100%; font:inherit; color:var(--ink);
    background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px 12px; outline:none; }}
  .opts select:focus, .opts input[type=text]:focus {{ border-color:var(--acc); }}
  .opts .ck {{ display:flex; align-items:center; gap:8px; font-size:13px; color:var(--mut); margin-top:16px; }}
  .opts .ck input {{ width:auto; }}
  .err {{ background:#fff0f0; border:1px solid #ffd2d2; color:var(--err); border-radius:12px;
    padding:10px 14px; margin-bottom:16px; font-size:14px; }}
  .notice {{ background:#fff8e1; border:1px solid #f0d9a0; color:#7a5b00; border-radius:12px;
    padding:11px 14px; margin:0 0 22px; font-size:13px; line-height:1.6; text-align:center; }}
  .notice code {{ background:rgba(0,0,0,.06); padding:1px 6px; border-radius:6px; }}
  .go.disabled {{ background:#c7c7cc; cursor:not-allowed; }}
  .foot {{ margin-top:28px; text-align:center; color:#a1a1a6; font-size:12px; line-height:1.7; }}
  .foot code {{ background:rgba(0,0,0,.05); padding:1px 6px; border-radius:6px; }}
  .loadbox {{ margin-top:22px; padding:18px; border:1px dashed var(--line);
    border-radius:14px; background:#fff; text-align:center; }}
  .loadtitle {{ font-size:15px; font-weight:600; margin:0 0 6px; }}
  .loadsub {{ font-size:13px; color:var(--mut); margin:0 0 14px; line-height:1.6; }}
  .loadrow {{ display:flex; gap:10px; justify-content:center; align-items:center; flex-wrap:wrap; }}
  .loadbox input[type=file] {{ font:13px/1 inherit; max-width:230px; }}
  .loadbtn {{ background:var(--ink); color:#fff; border:0; border-radius:980px;
    padding:10px 18px; font-size:14px; cursor:pointer; transition:opacity .15s; }}
  .loadbtn:hover {{ opacity:.88; }}
  a {{ color:var(--acc); }}
</style>
</head>
<body>
<div class="wrap">
  <p class="brand">Loom · 叙事编译器</p>
  <h1>把一句话变成一个能经得起检验的故事</h1>
  <p class="sub">不替你写。生成一版草稿，再用结构体检指出哪里站不住、哪里要合规——决定权在你。</p>
  {preview_notice}
  <form method="post" action="/">
    {err_banner}
    <textarea id="idea" name="idea" placeholder="一句话想法，例如：一个退休教师收到三十年前学生寄来的、还没写完的悔过书">{idea}</textarea>
    <div class="examples">{example_chips}</div>
    <button class="{go_cls}" type="submit"{go_dis}>{go_text}</button>

    <details class="more">
      <summary>更多选项</summary>
      <div class="opts">
        <label for="medium">媒介</label>
        <select id="medium" name="medium">
{medium_opts}
        </select>
        <label for="arc">情感弧线</label>
        <select id="arc" name="arc">
{arc_opts}
        </select>
        <label for="template">结构模板</label>
        <select id="template" name="template">
{template_opts}
        </select>
        <label for="scenes">场数</label>
        <select id="scenes" name="scenes">
          {_opt(scenes, 3)} {_opt(scenes, 5)} {_opt(scenes, 6)}
          {_opt(scenes, 8)} {_opt(scenes, 10)} {_opt(scenes, 12)}
        </select>
        <label for="words">每场目标字数</label>
        <select id="words" name="words">
          {_opt(words, 300)} {_opt(words, 500)} {_opt(words, 800)}
          {_opt(words, 1200)} {_opt(words, 2000)}
        </select>
        <label for="generator">驱动方式</label>
        <select id="generator" name="generator">
{generator_opts}
        </select>
        <p class="hint">「WorkBuddy 驱动」不需要 API key：Loom 把提示词写成待填文件，
        你（或任意聊天窗口）填完提交即可产出真内容。</p>
        <label for="model">模型（选「真模型」时填；留空 = 离线确定性参考实现）</label>
        <input type="text" id="model" name="model" value="{model}" placeholder="例如 gpt-4o / claude-3-5-sonnet">
        <label class="ck">
          <input type="checkbox" name="force_prose" {force_prose}>
          强制生成网文正文（默认按平台合规策略挡住）
        </label>
      </div>
    </details>
  </form>

  <div class="loadbox">
    <p class="loadtitle">已经有写好的 IR？</p>
    <p class="loadsub">载入一个 <code>ir.json</code>，直接在浏览器里看它的结构体检报告。</p>
    <div class="loadrow">
      <input type="file" id="irfile" accept=".json,application/json">
      <button type="button" class="loadbtn" id="loadbtn">载入已有 IR 文件</button>
    </div>
    <p class="hint" id="loadhint">文件只在本机解析，不会上传。</p>
  </div>

  <p class="foot">
    数据不出本机（仅监听 127.0.0.1）· 关闭窗口或按 Ctrl+C 即停止<br>
    想用命令行？运行 <code>loom "一句话想法"</code>
  </p>
</div>
<script>
(function(){{
  var btn=document.getElementById('loadbtn');
  var file=document.getElementById('irfile');
  var hint=document.getElementById('loadhint');
  if(!btn){{return;}}
  btn.addEventListener('click',function(){{
    if(!file||!file.files.length){{hint.textContent='请先选择一个 ir.json 文件。';return;}}
    var r=new FileReader();
    r.onerror=function(){{hint.textContent='读取文件失败。';}};
    r.onload=function(){{
      hint.textContent='正在解析并生成报告…';
      var fd=new URLSearchParams();
      fd.set('ir',r.result);
      fetch('/load',{{method:'POST',
        headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
        body:fd.toString()}})
        .then(function(res){{return res.text();}})
        .then(function(t){{document.open();document.write(t);document.close();}})
        .catch(function(e){{hint.textContent='载入失败：'+(e&&e.message?e.message:e);}});
    }};
    r.readAsText(file.files[0]);
  }});
}})();
</script>
</body>
</html>"""


#: 默认首屏（索引页）渲染入口。**稳定名字**，供测试与 `do_GET('/')` 共用，
#: 不随内部重构漂移。它不要求用户粘贴 JSON —— 首屏是一句话输入框 +
#: 「载入已有 IR 文件」两个低门槛入口。
render_index = build_form_page


def build_pending_page(
    *,
    queue_id: str,
    asks: list[dict],
    idea: str,
    errors: dict[str, str] | None = None,
    done: list[str] | None = None,
) -> str:
    """「Loom 在等你」那一页：逐条列出待填请求。

    为什么单独一页而不是塞进表单：这是 workbuddy 驱动的**主界面**，
    不是错误页。它要能让人（或让一个聊天窗口）看清楚「Loom 到底问了什么」，
    并把答案原样交回去。把它做成红色报错条，等于在说「你操作错了」——
    而实际上一切正常，只是轮到你了。

    `asks` 里每条带 _task / _index / _version / _system / _prompt / key。
    """
    errors = errors or {}
    done = done or []
    blocks: list[str] = []
    for i, a in enumerate(asks):
        key = a["key"]
        err = errors.get(key)
        prompt = html.escape(a.get("_prompt", ""), quote=False)
        system = html.escape(a.get("_system", ""), quote=False)
        blocks.append(
            f'<details class="ask"{" open" if i == 0 else ""}>'
            f'<summary><b>{html.escape(key)}</b>'
            f'<span class="tag">{html.escape(a.get("_task", ""))} · '
            f'{html.escape(str(a.get("_prompt_version", "")))}</span></summary>'
            f'<div class="askbody">'
            f'<p class="sys">{system}</p>'
            f'<pre>{prompt}</pre>'
            f'<textarea name="ans_{html.escape(key, quote=True)}" '
            f'placeholder=\'在这里粘贴 JSON，例如 {{"logline": "..."}}\'></textarea>'
            + (f'<p class="err">{html.escape(err)}</p>' if err else "")
            + "</div></details>"
        )

    done_note = ""
    if done:
        done_note = (
            '<p class="ok">已填好并沿用：'
            + "、".join(html.escape(k) for k in done)
            + "</p>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Loom · 等你填 {len(asks)} 个请求</title>
<style>
  :root {{
    --bg:#f5f5f7; --ink:#1d1d1f; --mut:#6e6e73; --line:#d2d2d7;
    --acc:#0071e3; --acc-h:#0077ed; --err:#d70015;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:32px 20px 60px; }}
  h1 {{ font-size:24px; font-weight:600; letter-spacing:-.3px; margin:0 0 8px; }}
  .sub {{ font-size:14px; color:var(--mut); margin:0 0 8px; line-height:1.7; }}
  .idea {{ font-size:14px; color:var(--mut); background:#fff; border:1px solid var(--line);
    border-radius:12px; padding:12px 14px; margin:0 0 22px; }}
  .ask {{ background:#fff; border:1px solid var(--line); border-radius:14px;
    margin-bottom:12px; overflow:hidden; }}
  .ask > summary {{ cursor:pointer; padding:14px 16px; font-size:15px; }}
  .tag {{ float:right; color:var(--mut); font-size:12px; font-weight:400; }}
  .askbody {{ padding:0 16px 16px; }}
  .sys {{ font-size:13px; color:var(--mut); margin:0 0 10px; line-height:1.6; }}
  pre {{ white-space:pre-wrap; word-break:break-word; background:#fafafa;
    border:1px solid var(--line); border-radius:10px; padding:12px;
    font-size:12.5px; line-height:1.6; max-height:340px; overflow:auto; margin:0 0 12px; }}
  textarea {{ width:100%; min-height:110px; border:1px solid var(--line);
    border-radius:12px; padding:12px; font:13px/1.6 ui-monospace,Menlo,Consolas,monospace; resize:vertical; }}
  .go {{ margin-top:18px; width:100%; background:var(--acc); color:#fff; border:0;
    border-radius:980px; padding:16px; font-size:17px; cursor:pointer; }}
  .go:hover {{ background:var(--acc-h); }}
  .err {{ color:var(--err); font-size:13px; margin:8px 0 0; }}
  .ok {{ color:#0a7d33; font-size:13px; background:#eefaf1; border:1px solid #bfe6cb;
    border-radius:10px; padding:10px 12px; }}
  .foot {{ margin-top:24px; color:#a1a1a6; font-size:12px; line-height:1.7; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Loom 在等你：{len(asks)} 个请求</h1>
  <p class="sub">Loom 不发请求，它发问题。下面每条都是它渲染好的提示词 ——
  填进 JSON 提交即可。留空的会保持待填，已填的不会丢。</p>
  <p class="idea">想法：{html.escape(idea)}</p>
  {done_note}
  <form method="post" action="/answer">
    <input type="hidden" name="q" value="{html.escape(queue_id, quote=True)}">
    {"".join(blocks)}
    <button class="go" type="submit">提交并继续生成</button>
  </form>
  <p class="foot">
    队列文件：<code>out/.wb_queue/{html.escape(queue_id, quote=True)}/{ANSWERS_NAME}</code><br>
    数据不出本机（仅监听 127.0.0.1）
  </p>
</div>
</body>
</html>"""


def _opt(selected: str, value: int) -> str:
    return (
        f'<option value="{value}"'
        f'{" selected" if str(selected) == str(value) else ""}>{value}</option>'
    )


def _make_handler(writer, base_out: Path):
    """工厂：把 writer 与输出根目录闭包进 handler 类（避免全局可变状态）。"""

    base_resolved = base_out.resolve()

    class LoomHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
        server_version = "LoomLocal/1.0"

        # -- GET --
        def do_GET(self) -> None:  # noqa: N802
            try:
                self._handle_get()
            except Exception as exc:  # 任何未预期异常都回到友好页，绝不裸 traceback（P-21）
                self._send_friendly_error(exc)

        def _handle_get(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            # `/load` 只接受 POST；直接访问时回首页（带说明的表单）。
            if parsed.path in ("/", "/index.html", "/load"):
                self._send_html(build_form_page().encode("utf-8"))
            elif parsed.path.startswith("/out/"):
                self._serve_file(parsed.path)
            else:
                self._send_404()

        # -- POST（生成 / 交答案 / 载入 IR）--
        def do_POST(self) -> None:  # noqa: N802
            try:
                self._handle_post()
            except Exception as exc:  # 同上：裸 traceback 对一个非技术用户 = 软件坏了
                self._send_friendly_error(exc)

        def _handle_post(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8", "replace")
            data = urllib.parse.parse_qs(raw, keep_blank_values=True)

            def gv(name: str, default: str = "") -> str:
                val = data.get(name)
                return val[0] if val else default

            path = urllib.parse.urlparse(self.path).path
            if path == "/load":
                self._do_load(gv)
                return
            if path == "/answer":
                self._do_answer(gv)
                return

            idea = gv("idea").strip()
            if not idea:
                self._send_html(
                    build_form_page(
                        values={k: gv(k) for k in ("medium", "arc", "template",
                                                  "scenes", "words", "model")},
                        error="请先写下一句话想法。",
                    ).encode("utf-8")
                )
                return

            generator = gv("generator", "workbuddy")
            model = gv("model").strip() or None
            if generator == "workbuddy":
                model = "workbuddy"
            elif generator == "mock":
                model = None  # 显式选了离线参考实现，就别让 model 字段偷偷接管

            params = {
                "idea": idea,
                "medium": gv("medium", "novel"),
                "arc": gv("arc", "man_in_a_hole"),
                "template": gv("template", "save_the_cat"),
                "scenes": _clamp_int(gv("scenes"), *_SCENES_RANGE),
                "words": _clamp_int(gv("words"), *_WORDS_RANGE),
                "model": model,
                "force_prose": ("force_prose" in data),
            }

            # 参数落盘：**重跑时必须能原样还原**，否则「填完再跑一次」会
            # 用默认参数重跑，前面的答案就对不上了（场数都不一样）。
            qdir = queue_dir_for(idea, base_resolved)
            if model == "workbuddy":
                qdir.mkdir(parents=True, exist_ok=True)
                (qdir / PARAMS_NAME).write_text(
                    json.dumps({**params, "generator": generator},
                               ensure_ascii=False),
                    encoding="utf-8",
                )

            try:
                result = writer(**params)
            except PendingGeneration:
                # 不是失败，是轮到人了。
                self._send_html(
                    self._pending_page(qdir, idea).encode("utf-8")
                )
                return
            except WorkBuddyAnswerError as exc:
                self._send_html(
                    build_form_page(
                        values=self._echo(idea, params, generator),
                        error=f"答案格式不对：{exc}",
                    ).encode("utf-8")
                )
                return
            except Exception as exc:  # 任何生成异常都回到表单，附错误，不崩溃服务
                self._send_html(
                    build_form_page(
                        values={
                            "idea": idea,
                            "medium": params["medium"],
                            "arc": params["arc"],
                            "template": params["template"],
                            "scenes": str(params["scenes"]),
                            "words": str(params["words"]),
                            "model": params["model"] or "",
                            "force_prose": "force_prose" if params["force_prose"] else "",
                        },
                        error=f"生成失败：{exc}",
                    ).encode("utf-8")
                )
                return

            self._redirect(result)

        # -- helpers --
        @staticmethod
        def _echo(idea: str, params: dict, generator: str) -> dict:
            """出错回填表单。**只写这一处**，否则每加一个字段就要改三遍。"""
            return {
                "idea": idea,
                "medium": params["medium"],
                "arc": params["arc"],
                "template": params["template"],
                "scenes": str(params["scenes"]),
                "words": str(params["words"]),
                "model": params["model"] or "",
                "generator": generator,
                "force_prose": "force_prose" if params["force_prose"] else "",
            }

        def _pending_page(self, qdir: Path, idea: str, errors=None) -> str:
            """读答案文件，分出「待填」与「已填」，渲染等待页。"""
            data = json.loads((qdir / ANSWERS_NAME).read_text(encoding="utf-8"))
            asks: list[dict] = []
            done: list[str] = []
            for key, val in data.items():
                if key.startswith("_") or not isinstance(val, dict):
                    continue
                if val.get("output") is None:
                    asks.append(
                        {"key": key,
                         **{k: v for k, v in val.items() if k != "output"}}
                    )
                else:
                    done.append(key)
            return build_pending_page(
                queue_id=qdir.name, asks=asks, idea=idea,
                errors=errors, done=done,
            )

        def _do_answer(self, gv) -> None:
            """把提交的答案写回队列，然后**重跑同一条流水线**。"""
            q = gv("q")
            # 队列 id 来自表单，必须当**不可信输入**处理：
            # 只允许队列目录名的形状（8 位十六进制），杜绝路径穿越。
            if not re.fullmatch(r"[0-9a-f]{8}", q):
                self._send_404()
                return
            qdir = base_resolved / ".wb_queue" / q
            if not (qdir / PARAMS_NAME).exists():
                self._send_404()
                return

            params = json.loads((qdir / PARAMS_NAME).read_text(encoding="utf-8"))
            params.pop("generator", None)
            idea = params["idea"]
            answers = json.loads((qdir / ANSWERS_NAME).read_text(encoding="utf-8"))

            errors: dict[str, str] = {}
            for key, val in answers.items():
                if key.startswith("_") or not isinstance(val, dict):
                    continue
                raw = gv("ans_" + key).strip()
                if not raw:
                    continue  # 留空 = 保持待填，不覆盖已有答案
                try:
                    val["output"] = json.loads(raw)
                except json.JSONDecodeError as exc:
                    errors[key] = f"不是合法 JSON：{exc}"

            (qdir / ANSWERS_NAME).write_text(
                json.dumps(answers, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if errors:
                # 有错的先摆出来，别拿半截答案去跑流水线。
                self._send_html(
                    self._pending_page(qdir, idea, errors=errors).encode("utf-8")
                )
                return

            try:
                result = writer(**params)
            except PendingGeneration:
                self._send_html(self._pending_page(qdir, idea).encode("utf-8"))
                return
            except WorkBuddyAnswerError as exc:
                self._send_html(
                    self._pending_page(qdir, idea,
                                       errors={"_": str(exc)}).encode("utf-8")
                )
                return
            self._redirect(result)

        def _do_load(self, gv) -> None:
            """载入本地 ir.json 并渲染它的结构体检报告（不跑生成流水线）。

            文件内容由前端 FileReader 读出、以 `ir` 字段 POST 上来，
            只在本机解析、不出网（铁律 6）。解析/渲染任一步出错都回到
            友好表单并附错误，不崩服务、不裸 traceback（P-21）。
            """
            raw_ir = (gv("ir") or "").strip()
            if not raw_ir:
                self._send_html(
                    build_form_page(
                        error="没有收到 IR 内容。请选择一个 ir.json 文件后再点"
                              "「载入已有 IR 文件」。"
                    ).encode("utf-8")
                )
                return
            try:
                from .ir.models import NarrativeIR
                ir = NarrativeIR.from_json(raw_ir)
            except Exception as exc:  # 坏 IR（截断 / 版本不对 / 字段非法）说人话
                self._send_html(
                    build_form_page(error=f"这份 IR 读不出来：{exc}").encode("utf-8")
                )
                return
            try:
                from .render import render_html
                out = render_html(ir)  # report=None 时内部自动跑 run_all
                # 加一个回首页的链接，免得用户在报告页里迷路。
                out = out.replace(
                    "</body>",
                    "<p style='text-align:center;margin:24px 0;'>"
                    "<a href='/'>← 回到 Loom 首页</a></p></body>",
                    1,
                )
            except Exception as exc:
                self._send_html(
                    build_form_page(error=f"生成报告失败：{exc}").encode("utf-8")
                )
                return
            self._send_html(out.encode("utf-8"))

        def _send_friendly_error(self, exc: Exception) -> None:
            """P-21：任何未预期异常都渲染成友好页，**绝不**把 Python traceback 甩给用户。"""
            etype = html.escape(type(exc).__name__, quote=True)
            msg = html.escape(str(exc)[:500], quote=True)
            body = (
                "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Loom · 出错了</title><style>"
                "body{margin:0;background:#f5f5f7;color:#1d1d1f;"
                "font:16px/1.6 -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;"
                "display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;}"
                ".c{background:#fff;border:1px solid #d2d2d7;border-radius:16px;padding:28px 30px;"
                "max-width:480px;text-align:center;}"
                "h1{font-size:22px;margin:0 0 12px;}p{color:#6e6e73;margin:8px 0;}"
                "code{background:#f0f0f3;padding:2px 6px;border-radius:6px;}"
                "a{color:#0071e3;}</style></head><body><div class='c'>"
                "<h1>出了点问题</h1>"
                "<p>页面没能正常显示，但你的数据还在本机、没有丢失。</p>"
                f"<p>错误类型：<code>{etype}</code></p>"
                f"<p>{msg}</p>"
                "<p>你可以<a href='/'>回到首页</a>重试，或检查后重新操作。</p>"
                "</div></body></html>"
            ).encode("utf-8")
            try:
                self.send_response(500)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                pass  # 连回写都失败就真的没办法了，至少别再抛

        def _redirect(self, result: dict) -> None:
            rel = result["outdir"].resolve().relative_to(base_resolved).as_posix()
            self.send_response(303)
            self.send_header(
                "Location", "/out/" + urllib.parse.quote(rel, safe="/") + "/loom.html"
            )
            self.end_headers()

        def _send_html(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_404(self) -> None:
            body = "<h1>404</h1><p>找不到这个地址。</p>".encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_file(self, path: str) -> None:
            rel = urllib.parse.unquote(path[len("/out/"):])
            target = (base_resolved / rel).resolve()
            # 防目录穿越：目标必须落在输出根目录内。
            if target != base_resolved and base_resolved not in target.parents:
                self._send_404()
                return
            if not target.is_file():
                self._send_404()
                return
            ctype = _CTYPES.get(target.suffix.lower(), "application/octet-stream")
            try:
                body = target.read_bytes()
            except OSError:
                self._send_404()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # 静音默认访问日志，保持终端干净
            return

    return LoomHTTPRequestHandler


def _warn_if_proxy_blocks_localhost(host: str) -> None:
    """本机地址 + 系统代理 = 浏览器打不开，这是「网页没法运转」最常见的根因。

    服务只绑 127.0.0.1，但浏览器若配置了 HTTP 代理且未绕过 localhost，
    请求会被送去代理（实测返回 502），页面就永远打不开。
    这里只能**明确告知并给出绕过办法** —— 用户的浏览器代理不在本进程控制范围内。
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        return
    proxy = (
        os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    )
    if not proxy:
        return
    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    if "127.0.0.1" in no_proxy or "localhost" in no_proxy:
        return
    print("  ⚠ 检测到系统代理，浏览器可能打不开本机地址：")
    print(f"    代理 = {proxy}")
    print("    请在浏览器/终端里让本机地址绕过代理，再打开上面的地址：")
    print("      Windows:     set NO_PROXY=127.0.0.1,localhost")
    print("      macOS/Linux: export no_proxy=127.0.0.1,localhost")


def serve(
    writer,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    base_out,
) -> None:
    """启动本地网页服务，直到 Ctrl+C。

    `writer` 是生成入口（CLI 那边传 `write_story`），签名：
        writer(idea, medium, arc, template, scenes, words, model, force_prose)
        -> dict（至少含 "outdir": Path）
    `base_out` 是产物根目录（表单生成的结果写在 `<base_out>/<slug>/`）。

    两个现实故障在这里显式处理（不是打磨项，是「起不来就完全用不了」）：
      * **端口被占用** —— 原来会直接抛一段 traceback，用户只看到「崩了」。
        现在给出人话提示与可用端口建议。
      * **系统代理拦本机地址** —— 见 `_warn_if_proxy_blocks_localhost`。
    """
    base_out = Path(base_out)
    base_out.mkdir(parents=True, exist_ok=True)
    handler = _make_handler(writer, base_out)

    # 端口自动退让：默认 8000 常被占用（本机实测就占着），而「起不来」
    # 对非技术用户等于「这软件坏了」。所以往后找空位，让它自己跑起来。
    httpd = None
    last_err: OSError | None = None
    for offset in range(_PORT_TRIES):
        candidate = port + offset
        try:
            httpd = http.server.ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            last_err = exc
            continue
        if offset:
            print(f"  （端口 {port} 被占用，已自动改用 {candidate}）")
        port = candidate
        break
    if httpd is None:
        print(
            f"\n  ✗ 起不来：端口 {port}–{port + _PORT_TRIES - 1} 都用不了"
            f"（{last_err}）。"
        )
        print("    手动指定一个空闲端口，例如：--port 9000")
        return

    url = f"http://{host}:{port}/"
    print(f"\n  Loom 网页界面已启动： {url}")
    print("  在浏览器打开上面的地址即可操作。按 Ctrl+C 停止。\n")
    _warn_if_proxy_blocks_localhost(host)

    # 自动开浏览器：把「知道有个地址」变成「已经看见了」（与生成后自动开枢纽同一条依据）。
    # 失败无妨 —— 地址已经打印在上面，用户可手动打开。
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止本地服务。")
    finally:
        httpd.server_close()
