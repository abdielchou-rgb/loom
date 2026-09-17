"""微短剧备案材料渲染器 —— 每集 AI 标识清单（A 层）。

依据：广电令16号《微短剧发展管理办法》(2026-09-01 施行) 第34条，
微短剧**每集**须显著标识 AI 生成内容。

铁律（honesty, iron law 7 + 22）：
    Loom **不是**法律/主管部门权威。本模块只产出「清单」（LIST），
    绝不产出「合规认证 / 保证」。所有输出必须携带
    「以主管部门最新口径为准」免责声明，且明确声明 Loom 不提供合规认证。

设计要点：
    * 场景(scene) == 集(episode)，对微短剧而言一一对应。
    * 非 micro_drama 媒介：返回 `[]`。这一清单只服务于微短剧，
      其它媒介不适用 —— SKIPPED ≠ PASS，交给调用方决定，不编造条目。
    * 渲染器只负责「从 IR 生成视图」，绝不反向修改 IR（与 text.py 同约）。
"""

from __future__ import annotations

from ..ir.enums import Medium
from ..ir.models import NarrativeIR

#: 广电令16号 第34条要求的每集 AI 生成标识文案。
AI_LABEL = "本集由人工智能辅助生成"

#: 法律出处（用于正文引用与脚注）。
CITATION = "广电令16号《微短剧发展管理办法》第34条"

#: 免责声明 —— 任何备案材料都必须携带，且 Loom 明确不提供合规认证。
DISCLAIMER = (
    "本清单由 Loom 自动生成，仅供参考，**以主管部门最新口径为准**。"
    "Loom 不提供合规认证。"
)


def build_filing_list(ir: NarrativeIR) -> list[dict]:
    """为微短剧产出「每集 AI 标识清单」。

    返回：每集一个 dict `{"episode": <1-based 序号>, "label": ..., "note": ...}`。

    非 `Medium.MICRO_DRAMA` 媒介返回 `[]`：该清单是微短剧专属，
    对其它媒介**不适用**而非「通过」。SKIPPED ≠ PASS —— 让调用方裁决，
    不伪造条目。
    """
    if ir.medium is not Medium.MICRO_DRAMA:
        return []

    rows: list[dict] = []
    for idx, scene in enumerate(ir.ordered_scenes(), start=1):
        rows.append(
            {
                "episode": idx,
                "label": AI_LABEL,
                "note": scene.title,  # 可选备注：集名（SceneNode.title 必填）
            }
        )
    return rows


def render_filing_markdown(ir: NarrativeIR) -> str:
    """渲染为 markdown 文档：标题 + 每集一行 + 免责脚注。

    脚注引用广电令16号 第34条，并携带「以主管部门最新口径为准」免责声明。
    """
    title = "微短剧 AI 生成标识清单（每集）"
    lines: list[str] = [
        f"# {title}",
        "",
        f"> 依据{CITATION}：微短剧每集须显著标识 AI 生成内容。",
        "",
        "| 集数 | AI 生成标识 | 备注 |",
        "| --- | --- | --- |",
    ]

    for row in build_filing_list(ir):
        lines.append(f"| {row['episode']} | {row['label']} | {row['note'] or ''} |")

    lines += [
        "",
        "---",
        "",
        DISCLAIMER,
        "",
    ]
    return "\n".join(lines)


def render_filing_csv(ir: NarrativeIR) -> str:
    """渲染为 CSV（episode,label），含表头。

    无场景（或适用媒介被跳过）时仍返回仅含表头的字符串，
    不伪造数据行。
    """
    rows = build_filing_list(ir)
    out: list[str] = ["episode,label"]
    for row in rows:
        out.append(f"{row['episode']},{row['label']}")
    return "\n".join(out)
