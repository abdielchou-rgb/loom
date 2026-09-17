"""溯源与 AI 参与度计量。

为什么这是架构必需件而非营销功能：

    第一层（**源**）《人工智能生成合成内容标识办法》
              国信办通字〔2025〕2 号 · **2025-09-01 施行**：
              显式标识 + 隐式标识（文件元数据须含生成合成属性、
              服务提供者名称或编码、内容编号）。**标识义务来自这里。**

    第二层（**流**）《微短剧发展管理办法》
              国家广电总局令第 16 号 · 2026-09-01 施行：
              第 34 条把上面的义务**落到微短剧场景** —— AI 参与制作生成的
              微短剧，须在每集醒目位置加注「AI 生成」提示标识。

    平台规则  起点中文网 2026-08-18：AI 内容占比超过 10% 即撤榜
              （前 1000 名撤约 100 本）。

> 两层不要混写。本项目此前把它们写成一条（「AI 参与须显著标识
> —— 微短剧办法」），结果是让 2025-09-01 就存在的义务看起来
> 2026-09-01 才出现。源与流分开引用，改动时才知道改的是哪一层。

结论：**无法证明 AI 参与度的产品，在中国市场是不可交付的。**
计量能力必须内建，且要能一键导出合规报告。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from ..ir.enums import ChunkOrigin
from ..ir.models import NarrativeIR, Provenance


@dataclass
class ParticipationReport:
    """AI 参与度报告。"""

    total_chars: int
    ai_chars: int
    human_chars: int
    mixed_chars: int
    by_origin: dict[str, int] = field(default_factory=dict)
    scene_count: int = 0
    traced_scenes: int = 0
    models_used: list[str] = field(default_factory=list)
    prompt_versions: list[str] = field(default_factory=list)

    @property
    def ai_ratio(self) -> float:
        return self.ai_chars / self.total_chars if self.total_chars else 0.0

    @property
    def human_ratio(self) -> float:
        return self.human_chars / self.total_chars if self.total_chars else 0.0

    @property
    def trace_coverage(self) -> float:
        return self.traced_scenes / self.scene_count if self.scene_count else 0.0

    def verdict(self) -> tuple[str, str]:
        """返回 (结论等级, 说明)。阈值可配置。"""
        if self.ai_ratio > 0.10:
            return (
                "BLOCKED",
                "AI 占比 >10%：触发起点撤榜规则，且短剧需强制 AI 标识。"
                "建议提高人工改写比例至 90% 以上。",
            )
        if self.ai_ratio > 0.05:
            return (
                "CAUTION",
                "AI 占比 5-10%：接近阈值。需保留完整溯源以备平台核查。",
            )
        return ("OK", "AI 占比 <5%：符合主流平台的可接受区间。")

    def render(self, title: str = "AI 参与度与合规报告") -> str:
        level, note = self.verdict()
        lines = [
            f"── {title} " + "─" * max(0, 40 - len(title)),
            f"  总字数           {self.total_chars:,}",
            f"  AI 生成/改写     {self.ai_chars:,}  ({self.ai_ratio:.2%})",
            f"  人机混合         {self.mixed_chars:,}",
            f"  纯人工           {self.human_chars:,}  ({self.human_ratio:.2%})",
            f"  溯源覆盖度       {self.trace_coverage:.0%}  ({self.traced_scenes}/{self.scene_count})",
        ]
        if self.models_used:
            lines.append(f"  涉及模型         {', '.join(self.models_used)}")
        if self.prompt_versions:
            lines.append(f"  提示词版本       {', '.join(self.prompt_versions)}")
        lines.append("─" * 56)
        lines.append(f"  结论 [{level}] {note}")
        return "\n".join(lines)

    def to_json(self) -> str:
        level, note = self.verdict()
        return json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "level": level,
                "note": note,
                "total_chars": self.total_chars,
                "ai_chars": self.ai_chars,
                "human_chars": self.human_chars,
                "mixed_chars": self.mixed_chars,
                "ai_ratio": round(self.ai_ratio, 4),
                "trace_coverage": round(self.trace_coverage, 4),
                "by_origin": self.by_origin,
                "models_used": self.models_used,
                "prompt_versions": self.prompt_versions,
            },
            ensure_ascii=False,
            indent=2,
        )


class ProvenanceLedger:
    """溯源台账。每一次生成/编辑都必须记账。"""

    def __init__(self) -> None:
        self.records: list[Provenance] = []

    def record(
        self,
        chunk_id: str,
        *,
        scene_id: str | None = None,
        origin: ChunkOrigin = ChunkOrigin.HUMAN,
        model_id: str | None = None,
        prompt_version: str | None = None,
        human_edit_ratio: float = 0.0,
        char_count: int = 0,
    ) -> Provenance:
        p = Provenance(
            chunk_id=chunk_id,
            scene_id=scene_id,
            origin=origin,
            model_id=model_id,
            prompt_version=prompt_version,
            human_edit_ratio=human_edit_ratio,
            char_count=char_count,
        )
        self.records.append(p)
        return p

    def attach(self, ir: NarrativeIR) -> None:
        """把台账写回 IR，并同步场景的 origin 字段。"""
        ir.provenance = list(self.records)
        for s in ir.scenes:
            for p in self.records:
                if p.scene_id == s.id:
                    s.origin = p.origin
                    s.model_id = p.model_id
                    s.prompt_version = p.prompt_version
                    break

    def report(self, ir: NarrativeIR) -> ParticipationReport:
        by_origin: dict[str, int] = {}
        ai_chars = human_chars = mixed_chars = 0

        for s in ir.scenes:
            n = len(s.prose or "")
            if not n:
                continue
            by_origin[s.origin.value] = by_origin.get(s.origin.value, 0) + n
            match s.origin:
                case ChunkOrigin.AI_GENERATED:
                    ai_chars += n
                case ChunkOrigin.AI_EDITED:
                    # AI 起草 + 人工修改：按编辑比例拆分
                    ratio = next(
                        (p.human_edit_ratio for p in self.records if p.scene_id == s.id),
                        0.5,
                    )
                    ai_chars += int(n * (1 - ratio))
                    mixed_chars += int(n * ratio)
                case ChunkOrigin.AI_ASSISTED:
                    # 人工主导 + AI 润色：全部计入人工
                    human_chars += n
                case _:
                    human_chars += n

        total = ai_chars + human_chars + mixed_chars
        traced = len({p.scene_id for p in self.records if p.scene_id})

        return ParticipationReport(
            total_chars=total,
            ai_chars=ai_chars,
            human_chars=human_chars,
            mixed_chars=mixed_chars,
            by_origin=by_origin,
            scene_count=len(ir.scenes),
            traced_scenes=traced,
            models_used=sorted({p.model_id for p in self.records if p.model_id}),
            prompt_versions=sorted(
                {p.prompt_version for p in self.records if p.prompt_version}
            ),
        )

    # ------------------------------------------------------------------
    # C2PA 出口 —— 把中国合规的溯源台账升级为全球标准内容凭证
    # ------------------------------------------------------------------

    def to_c2pa(self, ir: NarrativeIR) -> dict:
        """导出 C2PA 2.x 风格的内容凭证 manifest（纯数据，**未签名**）。

        把「源 / 流」两层合规的溯源台账，升级为**全球标准**的内容凭证结构
        （C2PA 2.x / CAWG Content Credentials）。Loom 只生产 manifest，
        **不签名** —— 签名需要 C2PA 凭证（X.509 证书），超出零依赖范围
        （铁律 6：硬依赖只有 pydantic）。导出后可交由支持 C2PA 的工具签名，
        再嵌入图片 / PDF / 视频的元数据。

        依据（成为全球顶级项目的路径调研）：全球 watermarking 强制令
        （EU AI Act 第 50 条 2026-08-02 生效、EU Code of Practice 2026-06-10、
        韩国 2026-03）把「可证明 AI 参与度」从中国市场义务变成了全球出海门槛。
        这一步让 Loom 的合规能力从「中国」变「全球」。
        """
        try:
            from importlib.metadata import version as _v

            lw = _v("loom")
        except Exception:
            from .. import __version__ as lw
        part = self.report(ir)
        actions: list[dict] = []
        ai_assertions: list[dict] = []
        for s in ir.scenes:
            if s.origin is ChunkOrigin.AI_GENERATED:
                action = "c2pa.generated"
            elif s.origin in (ChunkOrigin.AI_EDITED, ChunkOrigin.AI_ASSISTED):
                action = "c2pa.edited"
            else:
                action = "c2pa.created"
            actions.append(
                {
                    "action": action,
                    "part": f"scene:{s.id}",
                    "softwareAgent": {"name": "Loom", "version": lw},
                }
            )
            if s.origin is not ChunkOrigin.HUMAN:
                ai_assertions.append(
                    {
                        "part": f"scene:{s.id}",
                        "producedBy": {
                            "tool": {"name": "Loom", "version": lw},
                            "algorithm": {
                                "name": s.model_id or "llm-unspecified",
                                "version": "unknown",
                            },
                        },
                        "generated": s.origin is ChunkOrigin.AI_GENERATED,
                    }
                )
        return {
            "manifest": {
                "assertions": [
                    {"label": "c2pa.actions", "data": {"actions": actions}},
                    {
                        "label": "c2pa.assetGenAI",
                        "data": {
                            "version": "1.0",
                            "digitalSourceType": (
                                "http://cv.iptc.org/ns/digsrcType/"
                                "trainedAlgorithmicMedia"
                            ),
                            "generated": part.ai_ratio > 0,
                            "ai_ratio": round(part.ai_ratio, 4),
                            "assertions": ai_assertions,
                        },
                    },
                    {
                        "label": "c2pa.creativeWork",
                        "data": {
                            "title": ir.title,
                            "medium": ir.medium.value,
                            "tools": [{"name": "Loom", "version": lw}],
                        },
                    },
                    {
                        "label": "loom.participation",
                        "data": json.loads(part.to_json()),
                    },
                ]
            },
            "note": (
                "本 manifest 为 C2PA 2.x 兼容的内容凭证结构，但**未经签名**。"
                "签名需要 C2PA 凭证（X.509 证书），超出 Loom 零依赖范围"
                "（铁律 6：硬依赖只有 pydantic）。可导出后用支持 C2PA 的工具签名，"
                "再嵌入图片 / PDF / 视频的元数据。"
            ),
        }

    def to_c2pa_json(self, ir: NarrativeIR) -> str:
        return json.dumps(self.to_c2pa(ir), ensure_ascii=False, indent=2)
