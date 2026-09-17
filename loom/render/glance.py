"""第一分钟速览 —— 把「顶级内核」搬进「低门槛的壳」。

── 这个文件存在的理由（第一性原理）────────────────────────────

项目自审结论：内核顶级、外壳不及格，第一分钟可及性只有 3/10。
**成否系于一个变量：把资源从「再加门禁」转向「第一分钟体验」。**

一个到不了用户手里的判断价值为零。已有两个交付物（report.html 长报告、
process-report 申诉证据）都是「事后 / 深读」场景。新用户第一次打开 Loom，
他需要的不是 7 段体检明细，而是**一屏内能看懂、能转发的那张卡**：

    标题 + 一句话故事
    大纲（场景顺序 + 每场转折）
    三张人物卡（想要 / 需要 / 弧线 / 缺陷）
    体检头三行（结构分 + 最严重的 3 条）

目标：**一条命令 → 30 秒内 → 一屏可分享**。这是把前两条基础（架构正确性、
合规护城河）变成回报的**唯一**动作。

── 设计约束 ───────────────────────────────────────────────────
1. 自包含：不引 CDN / 外部字体 / JS。断网双击可看、可转发。
2. 一屏：用紧凑网格 + 小字号，桌面与手机都能在一屏内看完。
3. 不宣称做不到的事：明确这是「结构快照」不是质量评级；只报健康分，
   不报「会不会火」。
4. 不预测：体检头三行只列「已经查出来的结构问题」，不给改进建议排序。
"""

from __future__ import annotations

from html import escape

from ..ir.enums import Severity
from ..ir.models import NarrativeIR
from ..provenance.awareness import counts

__all__ = ["render_glance"]

_CSS = """
:root{--bg:#fbfaf8;--card:#fff;--ink:#1c1a17;--dim:#6b6560;--line:#e6e1da;
--err:#b3261e;--warn:#8a5a00;--ok:#2f6b3f;--accent:#2f4858}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 38px;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
"Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:22px;margin:0 0 2px;letter-spacing:.3px}
.sub{color:var(--dim);font-size:12px;margin-bottom:12px}
.row{display:grid;grid-template-columns:1.45fr 1fr;gap:14px}
@media(max-width:680px){.row{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:13px 15px;margin-bottom:12px}
h2{font-size:12px;margin:0 0 9px;color:var(--accent);text-transform:uppercase;
letter-spacing:.6px;border-bottom:2px solid var(--accent);padding-bottom:5px}
.chips{display:flex;gap:8px;margin:6px 0 13px;flex-wrap:wrap}
.chip{background:var(--card);border:1px solid var(--line);border-radius:20px;
padding:4px 12px;font-size:13px;color:var(--dim)}
.chip b{font-size:15px;color:var(--ink)}
.wf{color:var(--dim);font-size:12px}
ol.scn{margin:0;padding-left:20px}
ol.scn li{margin-bottom:5px}
ol.scn .tp{color:var(--dim);font-size:12px}
.pc{margin-bottom:9px;padding-bottom:9px;border-bottom:1px dashed var(--line)}
.pc:last-child{border-bottom:0;margin-bottom:0;padding-bottom:0}
.pc .nm{font-weight:600;font-size:14px}
.pc .ln{color:var(--dim);font-size:12px;margin-top:2px}
.f{font-size:12px;border-left:3px solid var(--line);padding:3px 0 3px 9px;margin-bottom:7px}
.f.err{border-color:var(--err)} .f.warn{border-color:var(--warn)}
.f .c{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.4px}
.f .m{margin:1px 0}
.foot{margin-top:22px;color:var(--dim);font-size:11px;border-top:1px solid var(--line);
padding-top:10px}
"""


def _score_color(n: int) -> str:
    if n >= 90:
        return "var(--ok)"
    if n >= 70:
        return "var(--warn)"
    return "var(--err)"


def render_glance(ir: NarrativeIR, report=None, *, title: str | None = None) -> str:
    """渲染为**单屏**速览卡。report 为 None 时现场跑一次体检。

    这是「第一分钟体验」的交付物：一屏可分享，不依赖浏览器之外任何资源。
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

    # ── 大纲：场景顺序 + 每场转折 ──
    outline_items: list[str] = []
    for i, s in enumerate(ir.ordered_scenes(), 1):
        tp = (s.turning_point or "").strip()
        outline_items.append(
            f"<li><b>{escape(s.title)}</b>"
            + (f"<span class='tp'> — {escape(tp[:54])}</span>" if tp else "")
            + "</li>"
        )

    # ── 三张人物卡 ──
    pcards: list[str] = []
    for c in list(ir.characters.characters.values())[:3]:
        pcards.append(
            "<div class='pc'>"
            f"<div class='nm'>{escape(c.name)}</div>"
            f"<div class='ln'>想要：{escape((c.want or '')[:40])}</div>"
            f"<div class='ln'>需要：{escape((c.need or '')[:40])}</div>"
            f"<div class='ln'>弧：{escape((c.arc_from or '')[:22])}"
            f" → {escape((c.arc_to or '')[:22])}</div>"
            + (f"<div class='ln'>缺陷：{escape((c.flaw or '')[:40])}</div>" if c.flaw else "")
            + "</div>"
        )
    if not pcards:
        pcards.append("<div class='ln'>（无角色）</div>")

    # ── 体检头三行：最严重的 3 条（错误优先）──
    fnds = [f for f in report.findings if f.severity in (Severity.ERROR, Severity.WARN)]
    top = sorted(
        fnds, key=lambda f: (0 if f.severity is Severity.ERROR else 1, f.code)
    )[:3]
    fhtml: list[str] = []
    if top:
        for f in top:
            cls = "err" if f.severity is Severity.ERROR else "warn"
            fhtml.append(
                f"<div class='f {cls}'><div class='c'>{escape(f.code)}</div>"
                f"<div class='m'>{escape(f.message[:90])}</div></div>"
            )
    else:
        fhtml.append(
            "<div class='f'><div class='m'>结构体检：无错误、无警告"
            "（头三行：干净）。</div></div>"
        )

    aw = counts(ir)

    parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{escape(title or ir.title)} · Loom 一屏速览</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        f"<h1>{escape(ir.title)}</h1>",
        f"<div class='sub'>Loom 一屏速览 · {escape(str(ir.medium))} · {ir.word_count()} 字</div>",
        "<div class='chips'>",
        f"<span class='chip'>结构分 <b style='color:{_score_color(score)}'>{score}</b>/100</span>",
        f"<span class='chip'>评估覆盖 <b>{cov:.0f}%</b>（{evaluated}/{total}）</span>",
        f"<span class='chip'>错误 {errs} · 警告 {warns}"
        + (f" · 提示 {infos}" if infos else "") + "</span>",
        f"<span class='chip'>人类判断 {aw['decided']}</span>",
        "</div>",
        "<div class='row'><div class='col'>",
        "<div class='card'><h2>大纲</h2>",
        f"<div class='wf' style='margin:0 0 8px'><b>一句话：</b>"
        f"{escape(com.logline or '—')}</div>",
        "<ol class='scn'>" + "".join(outline_items) + "</ol></div>",
        "</div><div class='col'>",
        "<div class='card'><h2>三张人物卡</h2>" + "".join(pcards) + "</div>",
        "</div></div>",
        "<div class='card'><h2>体检头三行</h2>" + "".join(fhtml) + "</div>",
        "<div class='foot'>Loom · 叙事编译器 · 一屏速览为<strong>结构快照</strong>，"
        "不是质量评级。你做了 "
        f"判断 {aw['decided']} · 采纳 {aw['accepted']} · 驳回 {aw['rejected']}"
        f" · 待裁决 {aw['pending']}。Loom 只做结构性淘汰，不预测作品会不会成功。</div>",
        "</div></body></html>",
    ]
    return "\n".join(parts)
