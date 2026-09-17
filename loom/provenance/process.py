"""创作过程报告 —— 把溯源从「免责证据」升级成「主张证据」。

── 两类证据（这个区分是本模块存在的理由）────────────────────

    **免责证据（exculpatory）**  「这一段不是 AI 写的」
                                 → Loom 已有：`ProvenanceLedger` 记 AI 占比

    **主张证据（assertive）**    「这些判断是人类做的」
                                 → Loom 此前**没有**

为什么后者更重要：平台误判时，作者要申诉的是「我确实参与了创作」。
「AI 只占 8%」是一条**被动**事实 —— 它只能说明剩下的 92% 不是 AI 写的，
说不出**人做了什么**。而「我驳回了 14 条 AI 提案、改了 6 处结构、
这两个场景是我手写的」是一条**主动**事实，它的证据力更强。

调研里平台给作者的实操建议明确写了「**留存创作过程**（提示词、修改记录、
迭代版本）是有价值的，真到申诉时都是证据」—— 那条建议指向的就是这一类。
但 Loom 原先的台账只有第一类，所以这一层必须补。

── 报告里有什么 ───────────────────────────────────────────

  1. AI 参与度与溯源覆盖率（免责证据）
  2. **人类判断清单**（主张证据）：每一条提案的裁决 —— 采纳 / 驳回 /
     标为冲突，附提案理由与作者的处理。这是「人确实在做决定」的直接凭据。
     每条都带**时间线**：机器何时提出 → 人何时裁决、谁裁的
     （`Diff.proposed_at` / `decided_at` / `decided_by`）。
  3. 人工原创场景清单
  4. 待裁决项（提醒：没裁决的东西不构成证据）
  5. **缺口声明**：本份报告**不能**证明什么 —— 见 `GAPS`

── 缺口声明为什么必须写 ─────────────────────────────────────

不写，这份报告就会被人当成「创作过程全记录」交上去，而它不是。
Loom 目前**没有**卡片级编辑历史、**没有**版本 diff；裁决时刻**有**了
（墙钟，见 `loom/clock.py`），但它是**自报**的 —— 不签名、不存证。
把这些写在报告里，作者才知道还该另外留什么。
一份不声明边界的证据，在申诉时会反噬：对方只要问出「那这一条你证明不了
什么」，整份材料的可信度都会跟着塌。

── 与 `selfcheck.py` 的分工 ─────────────────────────────────

    selfcheck       面向**投稿前**：法律义务 + 平台画像 + 待确认项
    本模块          面向**申诉时**：创作过程的证据链

两者都导出 JSON，但用途不同 —— 前者给作者自己看，后者给平台/编辑看。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from ..ir.enums import ChunkOrigin
from ..ir.models import NarrativeIR
from ..ir.proposal import DiffStatus
from .meter import ParticipationReport, ProvenanceLedger
from .telemetry import DecisionTelemetry

#: 本份报告**不能**证明的东西。导出时必须一起打印 ——
#: 一份不声明边界的证据，在申诉现场会被当成「你只有这些」。
#: 本文件导出时的时间戳（**自报**，见最后一条缺口）
GAPS: tuple[str, ...] = (
    "卡片级编辑历史：Loom 不记录「谁在什么时候把哪个字段从 A 改成 B」。"
    "要补这类证据，请自行保留 IR 的版本快照（每次大改导出一份 ir.json）。",
    "正文的逐字修改过程：Loom 只按场景记 origin，不记段内编辑。"
    "深度改写请保留自己的草稿。",
    "时间戳的**可信度**：本报告记录的是**墙钟时刻**（`Diff.proposed_at` / "
    "`Diff.decided_at`，见 `loom/clock.py`），但那是 Loom **自报**的 —— "
    "不签名、不做第三方存证，改系统时间即可改它。"
    "需要对抗性质疑时，请用第三方时间戳服务或可信存证，别只交这一份。",
    "外部工具链（灵感来源、素材、笔记）：不在 Loom 的能力范围内。",
)

#: 裁决状态 → 人读标签 + 它在申诉里意味着什么
_VERDICT_MEANING: dict[DiffStatus, str] = {
    DiffStatus.ACCEPTED: "作者采纳了这条 AI 提案（人认可了 AI 的建议）",
    DiffStatus.REJECTED: "作者驳回了这条 AI 提案（**这是最强的人类判断证据**）",
    DiffStatus.CONFLICTED: "作者标为冲突（AI 的建议与作者意图矛盾，由人裁定）",
}


@dataclass
class Judgement:
    """一条人类判断 —— 报告的核心单元。

    `proposed_at` / `decided_at` / `decided_by` 是**举证字段**：
    「我驳回了这个建议」是一句主张，「我在 2026-09-17T14:02:11+00:00
    驳回了它，它是在 14:01:03 由机器提出的」才是一份记录。
    三者缺失时判断仍成立（状态照常算数），但只具备态度价值 ——
    见 `undated`。
    """

    diff_id: str
    status: DiffStatus
    target_card: str
    field: str
    rationale: str
    source_card: str
    proposed_at: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None

    @property
    def meaning(self) -> str:
        return _VERDICT_MEANING.get(self.status, "")

    @property
    def dated(self) -> bool:
        """有没有时刻。**没有时刻的裁决在申诉现场会被打折扣** ——
        它证明不了「什么时候」，也就证明不了「那时稿子还没定稿」。"""
        return self.decided_at is not None

    def to_dict(self) -> dict:
        return {
            "id": self.diff_id,
            "status": self.status.value,
            "target_card": self.target_card,
            "field": self.field,
            "rationale": self.rationale,
            "source_card": self.source_card,
            "meaning": self.meaning,
            "proposed_at": self.proposed_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }


@dataclass
class CreativeProcessReport:
    title: str
    participation: ParticipationReport | None
    judgements: list[Judgement] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    human_scenes: list[str] = field(default_factory=list)
    ai_scenes: list[str] = field(default_factory=list)
    telemetry: dict | None = None

    # -- 汇总 --

    @property
    def decided(self) -> int:
        return len(self.judgements)

    @property
    def rejected(self) -> int:
        return sum(1 for j in self.judgements if j.status is DiffStatus.REJECTED)

    @property
    def accepted(self) -> int:
        return sum(1 for j in self.judgements if j.status is DiffStatus.ACCEPTED)

    @property
    def undated(self) -> int:
        """缺时刻的裁决条数。

        单列出来是因为它**不会**让上面那几个数变红 —— 一份「12 条裁决」
        的报告看起来很硬，若其中 12 条都没有时刻，它其实只证明
        「有人在某个时间做了些判断」，而「某个时间」正是申诉方会追问的。
        """
        return sum(1 for j in self.judgements if not j.dated)

    def evidence_strength(self) -> tuple[str, str]:
        """证据强度。**这是给作者的诚实评估，不是给平台的保证**。

        判据只用「人类判断的**数量**」，不用占比 —— 占比说不出人做了什么。
        """
        if self.decided == 0:
            return (
                "弱",
                "没有记录到任何人类裁决。本报告只能证明 AI 占比，"
                "**证明不了人的参与** —— 这正是最容易被判成 AI 代笔的形态。",
            )
        if self.rejected == 0 and self.decided < 3:
            return (
                "弱",
                f"只有 {self.decided} 条裁决且全部采纳。"
                "「AI 说什么就采纳什么」在申诉现场几乎不构成人类创作证据。",
            )
        if self.rejected >= 3:
            return (
                "较强",
                f"{self.decided} 条裁决，其中 {self.rejected} 条是**驳回** —— "
                "驳回是「人在做判断」最直接的证据。" + self._undated_note(),
            )
        return (
            "中",
            f"{self.decided} 条裁决（{self.accepted} 采纳 / {self.rejected} 驳回）。"
            "有人的判断，但驳回偏少 —— 补充对 AI 建议的**修改**会更有力。"
            + self._undated_note(),
        )

    def _undated_note(self) -> str:
        """缺时刻的提示。**没有时刻就要说出来**，否则「较强」这个评级
        会让作者以为可以只交这份报告 —— 而缺了时间维度的证据，对方一问
        「什么时候做的判断」就答不上来。"""
        if self.undated == 0:
            return ""
        return f"（⚠ 其中 {self.undated} 条**没有时刻**，举证力打折）"

    # -- 输出 --

    def render(self) -> str:
        L = [f"── {self.title} " + "─" * max(0, 36 - len(self.title))]
        L.append("")

        if self.participation:
            level, note = self.participation.verdict()
            L.append("  1. AI 参与度（免责证据）")
            L.append(f"     AI 占比        {self.participation.ai_ratio:.2%}")
            L.append(
                f"     溯源覆盖      {self.participation.trace_coverage:.0%}"
                f"（{self.participation.traced_scenes}/{self.participation.scene_count}）"
            )
            L.append(f"     结论 [{level}] {note}")
            L.append("")

        L.append("  2. 人类判断清单（主张证据）")
        if not self.judgements:
            L.append("     （无 —— 见下方证据强度）")
        else:
            for j in self.judgements:
                L.append(f"     · [{j.status.value}] {j.target_card}.{j.field}")
                L.append(f"       提案理由：{j.rationale}")
                L.append(f"       意味着：{j.meaning}")
                L.append(
                    f"       时间线：{j.proposed_at or '（未记录）'} 提出"
                    f" → {j.decided_at or '（未记录）'} "
                    f"由 {j.decided_by or '（未署名）'} 裁决"
                )
        L.append("")

        L.append("  3. 人工原创场景")
        L.append(
            f"     {len(self.human_scenes)} 场："
            + ("、".join(self.human_scenes) if self.human_scenes else "（无）")
        )
        if self.ai_scenes:
            L.append(f"     AI 参与 {len(self.ai_scenes)} 场：{'、'.join(self.ai_scenes)}")
        L.append("")

        if self.pending:
            L.append(f"  4. 待裁决（{len(self.pending)} 条，**不构成证据**）")
            L.append("     没裁决 = 没判断。要留给平台看，先把这些裁掉。")
            L.append("")

        level, note = self.evidence_strength()
        L.append("  证据强度：" + f"[{level}] {note}")
        L.append("")
        L.append("  ⚠ 本报告**不能**证明以下事情（缺口声明）：")
        for g in GAPS:
            L.append(f"     · {g}")
        return "\n".join(L)

    def to_markdown(self) -> str:
        """人读版本，可直接打印或作为申诉附件。"""
        L = [f"# {self.title}", ""]
        L.append(
            f"> 由 Loom 生成于 {datetime.now().isoformat(timespec='seconds')}。"
            "本文件记录创作过程中的人类判断，用于合规说明与申诉举证。"
        )
        L.append("")

        if self.participation:
            level, note = self.participation.verdict()
            L.append("## 1. AI 参与度")
            L.append("")
            L.append("| 项目 | 数值 |")
            L.append("|---|---|")
            L.append(f"| 总字数 | {self.participation.total_chars:,} |")
            L.append(f"| AI 生成 | {self.participation.ai_chars:,} |")
            L.append(f"| 纯人工 | {self.participation.human_chars:,} |")
            L.append(f"| AI 占比 | {self.participation.ai_ratio:.2%} |")
            L.append(
                f"| 溯源覆盖 | {self.participation.trace_coverage:.0%}"
                f"（{self.participation.traced_scenes}/{self.participation.scene_count}）|"
            )
            L.append(f"| 结论 | **{level}** — {note} |")
            L.append("")

        L.append("## 2. 人类判断清单")
        L.append("")
        if not self.judgements:
            L.append("_（无记录）_")
        else:
            L.append("| # | 目标卡 | 字段 | 裁决 | 提案理由 | 机器提出 | 人类裁决 | 裁决者 |")
            L.append("|---|---|---|---|---|---|---|---|")
            for i, j in enumerate(self.judgements, 1):
                rat = j.rationale.replace("|", "\\|").replace("\n", " ")[:80]
                L.append(
                    f"| {i} | `{j.target_card}` | `{j.field}` "
                    f"| **{j.status.value}** | {rat} "
                    f"| {j.proposed_at or '—'} "
                    f"| {j.decided_at or '—'} "
                    f"| {j.decided_by or '—'} |"
                )
            if self.undated:
                L.append("")
                L.append(
                    f"> ⚠ 其中 {self.undated} 条没有裁决时刻，"
                    "举证力打折（缺时间维度的证据答不出「什么时候做的判断」）。"
                )
        L.append("")
        L.append(
            "裁决语义："
            + "；".join(f"`{k.value}` = {v}" for k, v in _VERDICT_MEANING.items())
        )
        L.append("")

        L.append("## 3. 人工原创场景")
        L.append("")
        L.append(
            "、".join(f"`{s}`" for s in self.human_scenes) if self.human_scenes else "_（无）_"
        )
        L.append("")

        if self.pending:
            L.append(f"## 4. 待裁决（{len(self.pending)} 条）")
            L.append("")
            L.append("这些尚未裁决，**不构成人类判断的证据**。")
            L.append("")

        level, note = self.evidence_strength()
        L.append("## 证据强度")
        L.append("")
        L.append(f"**{level}** — {note}")
        L.append("")
        L.append("## 缺口声明")
        L.append("")
        L.append("本报告**不能**证明以下事情：")
        L.append("")
        for g in GAPS:
            L.append(f"- {g}")
        return "\n".join(L)

    def to_json(self) -> str:
        level, note = self.evidence_strength()
        return json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "title": self.title,
                "evidence_strength": {"level": level, "note": note},
                "participation": (
                    {
                        "ai_ratio": round(self.participation.ai_ratio, 4),
                        "trace_coverage": round(self.participation.trace_coverage, 4),
                        "level": self.participation.verdict()[0],
                    }
                    if self.participation
                    else None
                ),
                "judgements": [j.to_dict() for j in self.judgements],
                "undated_judgements": self.undated,
                "pending": self.pending,
                "human_scenes": self.human_scenes,
                "ai_scenes": self.ai_scenes,
                "telemetry": self.telemetry,
                "gaps": list(GAPS),
            },
            ensure_ascii=False,
            indent=2,
        )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def build_process_report(
    ir: NarrativeIR,
    *,
    telemetry: DecisionTelemetry | None = None,
    ledger: ProvenanceLedger | None = None,
) -> CreativeProcessReport:
    """组装一份创作过程报告。

    `telemetry` 可选：流水线路径上有它（内存台账，比 IR 里的 proposals
    多一个 `decided_at`）；CLI 路径上只有 IR。**两条路都要能出报告** ——
    申诉不会挑你当时走的是哪条路，所以不能让报告依赖内存状态。
    这也是本函数不把 telemetry 设为必填的原因。
    """
    if ledger is None:
        ledger = ProvenanceLedger()
        if ir.provenance:
            ledger.records = list(ir.provenance)
        else:
            for s in ir.scenes:
                ledger.record(
                    chunk_id=f"chunk_{s.id}",
                    scene_id=s.id,
                    origin=s.origin,
                    model_id=s.model_id,
                    prompt_version=s.prompt_version,
                    human_edit_ratio=0.0,
                    char_count=len(s.prose or ""),
                )
    part = ledger.report(ir)

    # -- 人类判断：从 IR 里**已裁决**的提案派生 --
    #
    # 为什么用 IR 的 proposals 而不是只用 telemetry：
    # telemetry 是进程内台账，导出 IR 再读回来就没了；
    # 而 `ir.proposals` 是**持久化**的（随 IR 一起存 JSON）。
    # 申诉发生在几天后，那时只有 IR 还在。
    judgements: list[Judgement] = []
    seen: set[str] = set()
    for d in ir.proposals:
        if d.status is DiffStatus.PENDING:
            continue
        seen.add(d.id)
        judgements.append(
            Judgement(
                diff_id=d.id,
                status=d.status,
                target_card=d.target_card,
                field=d.field,
                rationale=d.rationale,
                source_card=d.source_card,
                proposed_at=d.proposed_at,
                decided_at=d.decided_at,
                decided_by=d.decided_by,
            )
        )

    # telemetry 里可能有 IR 尚未同步的记录（同一次会话内），补进来
    if telemetry is not None:
        for rec in telemetry.records:
            if rec.status is DiffStatus.PENDING or rec.diff_id in seen:
                continue
            seen.add(rec.diff_id)
            judgements.append(
                Judgement(
                    diff_id=rec.diff_id,
                    status=rec.status,
                    target_card=rec.target_card,
                    field=rec.field,
                    rationale="（来自决策遥测，提案正文未随 IR 持久化）",
                    source_card=rec.source_card,
                    # 遥测里的 `story_at` 是**故事内**时点标签（「第 3 章」），
                    # 不是墙钟 —— 拿它当裁决时刻填进举证字段，等于把
                    # 「第 3 章」当成时间戳交给平台。此处留空，宁缺勿假。
                    decided_by=rec.decided_by,
                )
            )

    return CreativeProcessReport(
        title=f"{ir.title} · 创作过程报告",
        participation=part,
        judgements=judgements,
        pending=[d.id for d in ir.pending_proposals()],
        human_scenes=[s.id for s in ir.scenes if s.origin is ChunkOrigin.HUMAN],
        ai_scenes=[s.id for s in ir.scenes if s.origin is not ChunkOrigin.HUMAN],
        telemetry=telemetry.stats() if telemetry is not None else None,
    )
