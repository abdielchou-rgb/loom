"""一屏交互枢纽 —— 把散落产物汇成一张可导航的屏。

── 这个文件存在的理由（第一性原理）────────────────────────────

自审结论：内核顶级、外壳不及格，第一分钟可及性只有 3/10。
上一轮已经把 **glance**（可分享速览卡）与 **report.html**（深度报告）
接进 `write` 主路径，但两者仍是**独立文件**，用户打开后：
  - 不知道还有 c2pa.json / audience.json / process-report / bench 等产物；
  - 不知道每个产物对应哪条命令；
  - 要再敲命令才能挖更深，而命令墙本身就是 3/10 的根因。

本文件把「14 个子命令 + 一堆散落文件」收敛成**一张屏**：

    ┌─ 一屏枢纽 loom.html ───────────────────────────────┐
    │ 标题 + 一句话故事                                    │
    │ [结构分] [评估覆盖] [错误·警告·提示] [人类判断]        │
    │ ┌─ 结构地图(SVG) ─┐┌─ 人物卡×3+健康 ┐┌─ 命令面板 ⊞ ┐│
    │ │ 场景图+转折点    ││ want/need/arc  ││ ⌘K 搜动作   ││
    │ └─────────────────┘└───────────────┘│ 全部产物链接 ││
    │                                      └──────────────┘│
    └──────────────────────────────────────────────────────┘

它**不取代** glance（glance 是给外人转发的卡），而是 glance 的「主页」：
首屏只亮要点，命令面板可达全部 14 个动作。

── 设计约束（与 glance 同源，且更硬）──────────────────────────
1. 零依赖：纯 stdlib 生成 HTML + 内联 SVG + 内联 JS。不引 CDN / 外部字体 /
   外部 JS。**守铁律 6**（硬依赖只有 pydantic，LLM 可选）。
2. 命令面板用纯内联 JS（模糊过滤 + ⌘K/Ctrl+K 聚焦），不引任何库。
3. 结构地图用内联 SVG（场景节点 + 顺序边 + 转折点标签），零依赖。
4. 渐进披露：首屏只亮 3 个高频动作，其余在面板里可搜可达。
5. 不预测、不夸：明确这是「导航枢纽 + 结构快照」，不报「会不会火」。
"""

from __future__ import annotations

from html import escape

from ..ir.enums import Severity
from ..ir.models import NarrativeIR
from ..provenance.awareness import counts

__all__ = ["render_hub"]

_CSS = """
:root{--bg:#fbfaf8;--card:#fff;--ink:#1c1a17;--dim:#6b6560;--line:#e6e1da;
--err:#b3261e;--warn:#8a5a00;--ok:#2f6b3f;--accent:#2f4858;--link:#185fa5}
*{box-sizing:border-box}
body{margin:0;padding:22px 16px 40px;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
"Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:23px;margin:0 0 2px;letter-spacing:.3px}
.sub{color:var(--dim);font-size:12px;margin-bottom:11px}
.chips{display:flex;gap:8px;margin:4px 0 14px;flex-wrap:wrap}
.chip{background:var(--card);border:1px solid var(--line);border-radius:20px;
padding:4px 12px;font-size:13px;color:var(--dim)}
.chip b{font-size:15px;color:var(--ink)}
.grid{display:grid;grid-template-columns:1.05fr 1fr .95fr;gap:14px}
@media(max-width:780px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:13px 15px;margin-bottom:13px}
h2{font-size:12px;margin:0 0 9px;color:var(--accent);text-transform:uppercase;
letter-spacing:.6px;border-bottom:2px solid var(--accent);padding-bottom:5px}
.wf{color:var(--dim);font-size:12px}
svg.map{width:100%;height:auto;display:block}
.pc{margin-bottom:8px;padding-bottom:8px;border-bottom:1px dashed var(--line)}
.pc:last-child{border-bottom:0;margin-bottom:0;padding-bottom:0}
.pc .nm{font-weight:600;font-size:14px}
.pc .ln{color:var(--dim);font-size:12px;margin-top:2px}
.health{display:flex;gap:6px;margin-top:8px}
.hchip{flex:1;text-align:center;border:1px solid var(--line);border-radius:8px;
padding:5px 2px;font-size:11px;color:var(--dim)}
.hchip b{display:block;font-size:16px;color:var(--ink)}
.pal{position:sticky;top:10px}
#q{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:8px;
padding:8px 10px;font-size:13px;margin-bottom:8px;background:#fff;color:var(--ink)}
#q:focus{outline:none;border-color:var(--accent)}
.act{display:flex;justify-content:space-between;gap:8px;padding:5px 7px;
border-radius:6px;font-size:12.5px}
.act .cmd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent)}
.act .d{color:var(--dim);font-size:11px}
.act.hide{display:none}
.act:nth-child(odd){background:#f6f4f0}
.art a{display:block;padding:5px 7px;border-radius:6px;color:var(--link);
text-decoration:none;font-size:13px}
.art a:hover{background:#eef3f8}
.art a .sz{color:var(--dim);font-size:11px;margin-left:6px}
.foot{margin-top:20px;color:var(--dim);font-size:11px;border-top:1px solid var(--line);
padding-top:10px}
html{scroll-behavior:smooth}
.node{cursor:pointer}
.node:hover circle{stroke-width:2.5}
.scn{padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:8px}
.scn:target{border-color:var(--accent);background:#eef3f8}
.scn-h{font-weight:600;font-size:13px}
.scn-tag{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:10px;
padding:1px 8px;margin-left:6px}
.scn-tp{color:var(--dim);font-size:12px;margin-top:3px}
"""

# 命令面板：全部动作（含 happy path + 12 个子命令）。首屏只亮高频 3 个。
# 字段：(命令, 一句话说明, 是否高频首屏)
_ACTIONS: list[tuple[str, str, bool]] = [
    ("loom \"想法\"", "一句话想法 → IR → 正文/剧本，并打开本枢纽", True),
    ("loom glance <ir>", "生成可分享的一屏速览卡", True),
    ("loom c2pa <ir>", "导出 C2PA 内容凭证（合规溯源）", True),
    ("loom audit <ir>", "跑故事体检，列全部结构问题", False),
    ("loom report <ir>", "生成深度 HTML 报告", False),
    ("loom audience <ir>", "观众模拟：留存曲线 + 原话", False),
    ("loom render <ir> -f ink", "渲染为 Ink 互动小说", False),
    ("loom render <ir> -f fountain", "渲染为 Fountain 剧本", False),
    ("loom render <ir> -f renpy", "渲染为 Ren'Py galgame", False),
    ("loom outline <ir>", "输出纯大纲", False),
    ("loom proposals <ir>", "列出结构提案（待裁决）", False),
    ("loom decide <ir> --all", "一键采纳全部提案（唯一生效入口）", False),
    ("loom compliance <ir>", "合规画像", False),
    ("loom submit-check <ir>", "投稿前合规自检（能不能投）", False),
    ("loom process-report <ir>", "创作过程报告（申诉举证）", False),
    ("loom bench <ir>", "导出 loom-bench 校验器基准", False),
]


def _score_color(n: int) -> str:
    if n >= 90:
        return "var(--ok)"
    if n >= 70:
        return "var(--warn)"
    return "var(--err)"


def _scene_svg(ir: NarrativeIR, error_scene_ids: set[str] | None = None) -> str:
    """内联 SVG 结构地图：场景顺序节点 + 边 + 转折点标签。

    布局：每排最多 4 个节点，纵向排。节点圆形，边连接相邻，
    转折点放在节点下方（截断）。命中 ERROR 的场景描红边、填浅红。
    """
    scenes = ir.ordered_scenes()
    if not scenes:
        return "<p class='wf'>（无场景）</p>"

    err_ids = error_scene_ids or set()
    per_row = 4
    dxy = 92          # 节点水平间距
    dy = 96           # 行垂直间距
    r = 17
    ox = 30           # 左内边距
    oy = 26           # 上内边距

    rows = (len(scenes) + per_row - 1) // per_row
    width = ox * 2 + per_row * dxy
    height = oy * 2 + rows * dy

    # 高危场景：从 report 拿不到时（这里只传 ir）退化为不标红，
    # 但 hub 调 render_hub 会带 report，故标红在 _scene_svg 外做不方便。
    # 简化：结构地图只画顺序与转折点，颜色统一；问题由「体检头三行」承担。
    parts: list[str] = [
        f"<svg class='map' viewBox='0 0 {width} {height}' role='img'>"
    ]
    pos: dict[int, tuple[float, float]] = {}
    for i, s in enumerate(scenes):
        col = i % per_row
        row = i // per_row
        cx = ox + col * dxy + r
        cy = oy + row * dy + r
        pos[i] = (cx, cy)
        idx = escape(str(i + 1))
        bad = s.id in err_ids
        fill = "#FCEBEB" if bad else "#E6F1FB"
        stroke = "#A32D2D" if bad else "#378ADD"
        node = (
            f"<circle cx='{cx:.0f}' cy='{cy:.0f}' r='{r}' fill='{fill}' "
            f"stroke='{stroke}' stroke-width='1.5'/>"
            f"<text x='{cx:.0f}' y='{cy:.0f}' text-anchor='middle' "
            f"dominant-baseline='central' font-size='12' fill='#0c447c'>{idx}</text>"
        )
        tp = (s.turning_point or "").strip()
        if tp:
            tpe = escape(tp[:16])
            node += (
                f"<text x='{cx:.0f}' y='{cy + r + 11:.0f}' text-anchor='middle' "
                f"font-size='9.5' fill='#6b6560'>{tpe}</text>"
            )
        # 可点击：跳到本页「场景详情」锚点（见 render_hub 里的 .scn 块）
        parts.append(
            f"<a href='#scene-{escape(s.id)}' class='node' "
            f"aria-label='场景 {idx}：{escape((s.title or '')[:24])}'>{node}</a>"
        )
    # 顺序边
    for i in range(1, len(scenes)):
        a = pos[i - 1]
        b = pos[i]
        if (i % per_row) == 0:
            # 换行：从上一行末节点向下连到本行首节点
            parts.append(
                f"<path d='M{a[0]:.0f} {a[1] + r:.0f} "
                f"L{b[0]:.0f} {b[1] - r:.0f}' stroke='#9fb6c9' "
                f"stroke-width='1' fill='none'/>"
            )
        else:
            parts.append(
                f"<path d='M{a[0] + r:.0f} {a[1]:.0f} "
                f"L{b[0] - r:.0f} {b[1]:.0f}' stroke='#9fb6c9' "
                f"stroke-width='1' fill='none'/>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _scene_details(ir: NarrativeIR) -> str:
    """本页场景详情块，id 锚点与结构地图上的圈一一对应（点圈即跳转）。"""
    origin_label = {
        "ai_generated": "AI", "ai_assisted": "AI辅助", "human": "人",
        "ai_edited": "AI改", "imported": "导入",
    }
    blocks: list[str] = []
    for i, s in enumerate(ir.ordered_scenes()):
        outcome = s.outcome.value if s.outcome else "—"
        og = s.origin.value if s.origin else ""
        og_label = origin_label.get(og, og)
        blocks.append(
            "<div class='scn' id='scene-" + escape(s.id) + "'>"
            "<div class='scn-h'><b>场景 " + str(i + 1) + "</b> · "
            + escape(s.title or "") + " <span class='scn-tag'>" + escape(outcome) + "</span>"
            + (f" <span class='scn-tag'>{escape(og_label)}</span>" if og_label else "")
            + "</div>"
            "<div class='scn-tp'>转折：" + escape((s.turning_point or "—")[:80]) + "</div>"
            "</div>"
        )
    return "".join(blocks) if blocks else "<div class='wf'>（无场景）</div>"


def render_hub(
    ir: NarrativeIR,
    report=None,
    *,
    title: str | None = None,
    artifacts: list[tuple[str, str]] | None = None,
) -> str:
    """渲染**一屏交互枢纽**。report 为 None 时现场跑一次体检。

    这是 `write` 主路径默认产出的「主页」：把 glance / report / c2pa / audience
    等所有产物汇到一张可导航的屏，首屏只亮要点，命令面板可达全部动作。
    """
    if report is None:
        from ..validators import run_all

        report = run_all(ir)

    score = report.score()
    errs = len(report.errors)
    warns = len(report.warnings)
    infos = len(report.infos)
    evaluated = len(report.evaluated)
    skipped = len(report.skipped)
    crashed = len(report.crashes)
    total = evaluated + skipped + crashed
    cov = (evaluated / total * 100) if total else 0.0

    com = ir.commitment
    aw = counts(ir)
    error_scene_ids = {
        f.scene_id for f in report.findings if f.severity is Severity.ERROR and f.scene_id
    }

    # ── 人物卡 ×3 ──
    pcards: list[str] = []
    for c in list(ir.characters.characters.values())[:3]:
        pcards.append(
            "<div class='pc'>"
            f"<div class='nm'>{escape(c.name)}</div>"
            f"<div class='ln'>想要：{escape((c.want or '')[:40])}</div>"
            f"<div class='ln'>需要：{escape((c.need or '')[:40])}</div>"
            f"<div class='ln'>弧：{escape((c.arc_from or '')[:20])}"
            f" → {escape((c.arc_to or '')[:20])}</div>"
            + (f"<div class='ln'>缺陷：{escape((c.flaw or '')[:40])}</div>" if c.flaw else "")
            + "</div>"
        )
    if not pcards:
        pcards.append("<div class='ln'>（无角色）</div>")

    # ── 命令面板行 ──
    acts: list[str] = []
    for cmd, desc, hi in _ACTIONS:
        cls = "act" + ("" if hi else " more hide")
        acts.append(
            f"<div class='{cls}' data-c='{escape(cmd.lower())}'>"
            f"<span class='cmd'>{escape(cmd)}</span>"
            f"<span class='d'>{escape(desc)}</span></div>"
        )

    # ── 全部产物链接 ──
    if artifacts is None:
        artifacts = [
            ("ir.json", "叙事 IR（产品本体）"),
            ("report.html", "深度结构体检报告"),
            ("glance.html", "一屏可分享速览卡"),
            ("c2pa.json", "C2PA 内容凭证"),
            ("audience.json", "观众模拟结果"),
            ("outline.md", "纯大纲"),
        ]
    arts: list[str] = []
    for fn, label in artifacts:
        arts.append(
            f"<a href='{escape(fn)}'>{escape(label)}"
            f"<span class='sz'>{escape(fn)}</span></a>"
        )

    parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{escape(title or ir.title)} · Loom 枢纽</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        f"<h1>{escape(ir.title)}</h1>",
        f"<div class='sub'>Loom 一屏枢纽 · {escape(str(ir.medium))} · "
        f"{ir.word_count()} 字 · 一条命令 → 一屏可导航</div>",
        "<div class='chips'>",
        f"<span class='chip'>结构分 <b style='color:{_score_color(score)}'>{score}</b>/100</span>",
        f"<span class='chip'>评估覆盖 <b>{cov:.0f}%</b>（{evaluated}/{total}）</span>",
        f"<span class='chip'>错误 {errs} · 警告 {warns}"
        + (f" · 提示 {infos}" if infos else "") + "</span>",
        f"<span class='chip'>人类判断 {aw['decided']}</span>",
        "</div>",
        "<div class='grid'>",
        # 左：结构地图
        "<div class='col'><div class='card'><h2>结构地图</h2>"
        + _scene_svg(ir, error_scene_ids)
        + "<div class='wf' style='margin-top:6px'><b>一句话：</b>"
        f"{escape(com.logline or '—')}</div>"
        "<div class='wf' style='margin-top:8px'>场景详情（点地图上的圈可跳转）：</div>"
        + _scene_details(ir)
        + "</div></div>",
        # 中：人物卡 + 健康
        "<div class='col'><div class='card'><h2>三张人物卡</h2>"
        + "".join(pcards)
        + "<div class='health'>"
        f"<div class='hchip'>结构分<b>{score}</b></div>"
        f"<div class='hchip'>覆盖<b>{cov:.0f}%</b></div>"
        f"<div class='hchip'>错误<b>{errs}</b></div>"
        + "</div></div></div>",
        # 右：命令面板 + 产物
        "<div class='col'><div class='card pal'><h2>命令面板 ⊞</h2>"
        "<input id='q' placeholder='⌘K / Ctrl+K 搜索动作…' "
        "autocomplete='off' spellcheck='false'>"
        "<div id='acts'>" + "".join(acts) + "</div>"
        "<div style='text-align:center;margin-top:7px'>"
        "<a href='#' id='act-toggle' style='color:var(--dim);font-size:12px;text-decoration:none'>"
        "显示全部 ↓</a></div></div>"
        "<div class='card'><h2>全部产物</h2><div class='art'>"
        + "".join(arts) + "</div></div></div>",
        "</div>",
        "<div class='foot'>Loom · 叙事编译器 · 一屏枢纽为<strong>导航 + 结构快照</strong>，"
        "不是质量评级。你做了判断 "
        f"{aw['decided']} · 采纳 {aw['accepted']} · 驳回 {aw['rejected']}"
        f" · 待裁决 {aw['pending']}。Loom 只做结构性淘汰，不预测作品会不会成功。"
        "⌘K 可搜全部 16 个动作；首屏只亮高频 3 个，其余渐进可达。</div>",
        "</div>",
        "<script>",
        "(function(){var q=document.getElementById('q');"
        "var actsDiv=document.getElementById('acts');"
        "var toggle=document.getElementById('act-toggle');"
        "var acts=Array.prototype.slice.call(document.querySelectorAll('#acts .act'));"
        "function f(){var t=q.value.trim().toLowerCase();"
        "var showAll=actsDiv.classList.contains('show-all');"
        "acts.forEach(function(a){var hit=a.getAttribute('data-c').indexOf(t)>=0"
        "||a.textContent.toLowerCase().indexOf(t)>=0;"
        "var isMore=a.classList.contains('more');"
        "var shouldHide=!hit||(!showAll&&t===''&&isMore);"
        "a.classList.toggle('hide',shouldHide);});}"
        "q.addEventListener('input',f);"
        "document.addEventListener('keydown',function(e){"
        "if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){"
        "e.preventDefault();q.focus();q.select();}});"
        "if(toggle){toggle.addEventListener('click',function(e){"
        "e.preventDefault();actsDiv.classList.toggle('show-all');"
        "toggle.textContent=actsDiv.classList.contains('show-all')?'收起 ↑':'显示全部 ↓';"
        "f();});}"
        "f();})();",
        "</script>",
        "</body></html>",
    ]
    return "\n".join(parts)
