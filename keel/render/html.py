"""单文件 HTML 报告渲染器 —— 让体检结果第一次**被人看见**。

── 为什么要有这个渲染器（第一性原理）────────────────────────────
已有 5 个渲染器（fountain / ink / renpy / storyboard / text），**全是文本格式**。
29 个校验器 + 7 个报表项的结论只活在终端里，作者看完就关掉了。

第一性原理：

  > **一个到不了用户手里的判断，价值为零。**

「可达性」不是打磨项，是**乘数** —— 它乘在所有已有能力上。
35 个校验器如果没人看，等于 0 个。

外部依据：
  * **F7（门槛决定采用）**：InkOS（10 agent、37 维审计）在中文横评里只排第 8，
    原因是本地部署 + 命令行 + 门槛太高。Keel 比它更远。
  * **F5（a16z 留存重定基到 M3）**：M0–M3 是获客期，靠的是**分享**。
    一个能双击打开、能发给别人的文件，是 Keel 目前唯一现成的获客载体。

── 设计约束（每一条都是硬约束）──────────────────────────────────
1. **自包含**：不引 CDN、不引外部字体、不引 JS 库。断网双击可看。
   理由：目标是「发给别人」，任何外链都会在某些环境下变成白屏。
2. **不宣称做不到的事**：报告里明确区分
   「结构分（可验算）」/「工艺提示（只通报）」/「评估覆盖（有多少项真的跑了）」。
   只报健康分而不报覆盖率，等于隐瞒「有多少项没测」。
3. **觉察可见**（`awareness_block`）：依据 CHI 2026 *Reactive Writing* ——
   作者察觉不到 AI 的影响。报告里必须有独立区块显示「你做了多少判断」。
   只放创作过程报告（申诉用）是不够的，那份是**事后**才导出的。

── 刻意不做的事 ───────────────────────────────────────────────────
* **不做交互**（无 JS 逻辑、无折叠）：这是一份**快照**，不是应用。
  交互式看板是另一件事，不该由渲染器承担。
* **不预测爆款**、不给「改进建议清单」的排序：排序隐含价值判断，
  而本项目的立场是只做结构性淘汰，不做成功预测。
"""

from __future__ import annotations

from html import escape

from ..ir.enums import Severity
from ..ir.models import NarrativeIR
from ..provenance.awareness import awareness_block, counts

__all__ = ["render_html"]

#: 严重度 → (显示名, CSS 类)
_SEV_LABEL = {
    Severity.ERROR: ("错误", "err"),
    Severity.WARN: ("警告", "warn"),
    Severity.INFO: ("提示", "info"),
}

_CSS = """
:root{--bg:#fbfaf8;--card:#fff;--ink:#1c1a17;--dim:#6b6560;--line:#e6e1da;
--err:#b3261e;--warn:#8a5a00;--info:#3c6e8f;--ok:#2f6b3f;--accent:#2f4858}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--bg);color:var(--ink);
font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
"Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px;letter-spacing:.5px}
h2{font-size:16px;margin:34px 0 12px;padding-bottom:7px;
border-bottom:2px solid var(--accent);color:var(--accent)}
h3{font-size:14px;margin:18px 0 8px;color:var(--dim);font-weight:600}
.sub{color:var(--dim);font-size:13px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:14px}
.score{display:flex;align-items:baseline;gap:14px;margin:6px 0 2px}
.score .n{font-size:52px;font-weight:700;line-height:1;letter-spacing:-1px}
.score .d{color:var(--dim);font-size:14px}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:12px}
.bar i{display:block;height:100%;border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kv{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kv .k{color:var(--dim);font-size:12px;margin-bottom:3px}
.kv .v{font-size:15px;font-weight:600}
.f{border-left:3px solid var(--line);padding:8px 0 8px 12px;margin-bottom:10px}
.f.err{border-color:var(--err)} .f.warn{border-color:var(--warn)}
.f.info{border-color:var(--info)}
.f .c{font-size:11px;letter-spacing:.4px;color:var(--dim);text-transform:uppercase}
.f .m{margin:2px 0}
.f .s{color:var(--dim);font-size:13px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;
border:1px solid var(--line);color:var(--dim);margin-left:6px}
.ok{color:var(--ok)} .dim{color:var(--dim)}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--dim);font-size:12px;font-weight:600}
.foot{margin-top:38px;padding-top:14px;border-top:1px solid var(--line);
color:var(--dim);font-size:12px}
.note{background:#f4f1ec;border:1px solid var(--line);border-radius:8px;
padding:11px 14px;font-size:13px;color:var(--dim);margin:10px 0}
pre{white-space:pre-wrap;word-break:break-word;margin:0;font:inherit}
ul{margin:6px 0;padding-left:20px}
"""


def _score_color(n: int) -> str:
    if n >= 90:
        return "var(--ok)"
    if n >= 70:
        return "var(--warn)"
    return "var(--err)"


def _findings_html(items: list, title: str, note: str = "") -> str:
    if not items:
        return f"<h3>{escape(title)}</h3><p class='dim'>无</p>"
    out = [f"<h3>{escape(title)}</h3>"]
    if note:
        out.append(f"<p class='note'>{escape(note)}</p>")
    for f in items:
        label, cls = _SEV_LABEL.get(f.severity, ("提示", "info"))
        out.append(
            f"<div class='f {cls}'>"
            f"<div class='c'>{escape(f.code)}"
            f"<span class='tag'>{escape(label)}</span>"
            + (f"<span class='tag'>{escape(f.scene_id)}</span>" if f.scene_id else "")
            + "</div>"
            f"<div class='m'>{escape(f.message)}</div>"
            + (f"<div class='s'>→ {escape(f.suggestion)}</div>" if f.suggestion else "")
            + "</div>"
        )
    return "\n".join(out)


def render_html(ir: NarrativeIR, report=None, *, title: str | None = None) -> str:
    """渲染为**单文件** HTML 报告，自包含、断网可看。

    `report` 为 `None` 时现场跑一次体检（`run_all`）。
    """
    if report is None:
        from ..validators import run_all

        report = run_all(ir)

    score = report.score()
    errs = len(report.errors)
    warns = len(report.warnings)
    infos = sum(1 for f in report.findings if f.severity is Severity.INFO)

    evaluated = len(getattr(report, "evaluated", []) or [])
    skipped = len(report.skipped or {})
    crashed = len(report.crashes or {})
    total = evaluated + skipped + crashed
    cov = (evaluated / total * 100) if total else 0.0

    c = counts(ir)
    pend = [d for d in ir.proposals if getattr(d, "status", None) is not None
            and getattr(d.status, "value", "") == "pending"]

    parts: list[str] = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{escape(title or ir.title)} · Keel 报告</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        f"<h1>{escape(ir.title)}</h1>",
        f"<div class='sub'>Keel 叙事编译报告 · {escape(str(ir.medium))} · "
        f"{ir.word_count()} 字</div>",
        # ── 1. 结构健康分 ──
        "<h2>结构健康分</h2><div class='card'>",
        f"<div class='score'><span class='n' style='color:{_score_color(score)}'>"
        f"{score}</span><span class='d'>/ 100 · 错误 {errs} · 警告 {warns} · 提示 {infos}"
        "</span></div>",
        f"<div class='bar'><i style='width:{max(0, min(100, score))}%;"
        f"background:{_score_color(score)}'></i></div>",
        "<p class='note'>这个分数**只表示结构**。工艺 / 文风 / 可读性信号在下方"
        "「非结构信号」里，不进这个分数 —— 否则多装几个检测器就会无声地把它推低，"
        "而读者分不清是「结构变差了」还是「多装了检查」。</p>",
        "</div>",
        # ── 2. 评估覆盖（必须与分数并列）──
        "<h2>评估覆盖</h2><div class='card'>",
        f"<div class='grid'>"
        f"<div class='kv'><div class='k'>跑过</div><div class='v'>{evaluated}</div></div>"
        f"<div class='kv'><div class='k'>跳过（缺数据）</div><div class='v'>{skipped}</div></div>"
        f"<div class='kv'><div class='k'>崩溃</div><div class='v'>{crashed}</div></div>"
        f"<div class='kv'><div class='k'>覆盖率</div><div class='v'>{cov:.0f}%</div></div>"
        "</div>",
        "<p class='note'>只报健康分而不报覆盖率，等于隐瞒「有多少项根本没测」。</p>",
    ]
    if report.skipped:
        parts.append("<table><tr><th>跳过项</th><th>缺什么</th></tr>")
        for code, missing in report.skipped.items():
            parts.append(
                f"<tr><td>{escape(code)}</td>"
                f"<td class='dim'>{escape('，'.join(missing))}</td></tr>"
            )
        parts.append("</table>")
    if report.crashes:
        parts.append(
            f"<p class='f err'><b>校验器崩溃 {crashed} 个。</b> 这是 Keel 的缺陷，"
            f"不是这个故事的缺陷，因此<b>不扣健康分</b>。"
            f"<br><span class='dim'>{escape('；'.join(report.crashes.values()))}</span></p>"
        )
    parts.append("</div>")

    # ── 3. 人类判断痕迹（觉察）──
    parts.append("<h2>人类判断痕迹</h2><div class='card'>")
    parts.append("<pre>" + escape("\n".join(awareness_block(ir))) + "</pre>")
    parts.append(
        "<p class='note'>CHI 2026（<i>Reactive Writers</i>，19 人访谈 + 1,291 次"
        "协同写作会话）发现：作者<b>察觉不到</b> AI 对自己方向的影响，却感觉完全掌控 ——"
        "因为在原则上他们随时可以编辑最终文本。这一块让「你做了多少判断」"
        "在<b>看报告时</b>可见，而不是申诉时才导出。</p>"
    )
    parts.append(
        f"<div class='grid' style='margin-top:12px'>"
        f"<div class='kv'><div class='k'>已裁决</div><div class='v'>{c['decided']}</div></div>"
        f"<div class='kv'><div class='k'>采纳</div><div class='v'>{c['accepted']}</div></div>"
        f"<div class='kv'><div class='k'>驳回</div><div class='v'>{c['rejected']}</div></div>"
        f"<div class='kv'><div class='k'>待裁决</div><div class='v'>{c['pending']}</div></div>"
        "</div></div>"
    )

    # ── 4. 三层 IR ──
    com = ir.commitment
    parts.append("<h2>叙事前提（L3 承诺层）</h2><div class='card'>")
    for k, v in (
        ("前提（Egri 因果断言）", com.premise),
        ("控制理念（McKee）", com.controlling_idea),
        ("一句话故事", com.logline),
    ):
        if v:
            parts.append(
                f"<div style='margin-bottom:9px'><div class='k dim' style='font-size:12px'>"
                f"{escape(k)}</div><div>{escape(str(v))}</div></div>"
            )
    if com.commitments:
        parts.append("<h3>必须发生的事（作者承诺）</h3><table>"
                     "<tr><th>类型</th><th>内容</th><th>落点</th><th>作者标记</th></tr>")
        for cm in com.commitments:
            # 「是否真的兑现」**不可机判**（见 validators/structure.commitment_satisfied
            # 的 docstring 与实测）。所以这里只报**两件可确证的事**：承诺挂在哪一场、
            # 作者有没有标记它兑现。
            # 曾经这里印「已兑现 / 未兑现」—— 那是把一个**声明式字段**说成了判定结果，
            # 而实测该判定在中文上恒假（7/7 误报）。
            anchors = "、".join(cm.must_hold_at or []) or "—"
            st = "已标记兑现" if cm.satisfied else "未标记"
            col = "var(--ok)" if cm.satisfied else "var(--dim)"
            parts.append(
                f"<tr><td>{escape(str(cm.kind))}</td><td>{escape(cm.statement)}</td>"
                f"<td>{escape(anchors)}</td>"
                f"<td style='color:{col}'>{st}</td></tr>"
            )
        parts.append("</table>")
        parts.append(
            "<div class='dim' style='font-size:12px;margin-top:6px'>"
            "注：「是否真的兑现」不可自动判定 —— 承诺是抽象主题句，正文是具体动作句，"
            "两者措辞本就不重合。此表只报可确证的两件事：承诺的落点、作者自己的标记。"
            "</div>"
        )
    parts.append("</div>")

    # ── 5. 体检明细 ──
    parts.append("<h2>体检明细</h2><div class='card'>")
    parts.append(
        _findings_html(
            [f for f in report.findings if f.severity is Severity.ERROR],
            "错误",
            "结构性错误 —— 故事在这些地方不成立。",
        )
    )
    parts.append(
        _findings_html(
            [f for f in report.findings if f.severity is Severity.WARN], "警告"
        )
    )
    parts.append(
        _findings_html(
            [f for f in report.findings if f.severity is Severity.INFO], "提示"
        )
    )
    parts.append("</div>")

    # ── 6. 非结构信号 ──
    parts.append("<h2>非结构信号（不计入健康分）</h2><div class='card'>")
    parts.append(
        _findings_html(
            report.advisory,
            f"共 {len(report.advisory)} 条",
            "工艺 / 文风 / 可读性 / 平台合规向信号。它们值得看，但不是结构缺陷，"
            "因此不进上面的分数。",
        )
    )
    parts.append("</div>")

    # ── 7. 待裁决提案 ──
    parts.append("<h2>待裁决提案</h2><div class='card'>")
    if pend:
        parts.append(
            f"<p class='note'>{len(pend)} 条 AI 提案在等你裁决。"
            "Keel <b>不会</b>自动应用结构类改动 —— 自动改结构会毁掉作者意图，"
            "而且经验上也做不好（图规划路线在前提忠实度上只有 40%）。</p>"
        )
        parts.append("<table><tr><th>字段</th><th>现状</th><th>提议</th><th>理由</th></tr>")
        for d in pend:
            parts.append(
                f"<tr><td>{escape(str(d.field))}</td>"
                f"<td>{escape(str(d.before))}</td>"
                f"<td>{escape(str(d.after))}</td>"
                f"<td class='dim'>{escape(str(d.rationale))}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p class='dim'>无待裁决提案。</p>")
    parts.append("</div>")

    parts.append(
        "<div class='foot'>Keel · 叙事编译器 · 本报告为<strong>结构快照</strong>，"
        "不是质量评级。Keel 只做结构性淘汰，不预测作品会不会成功。</div>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)
