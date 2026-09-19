"""小说正文渲染器。

关键设计：渲染器只负责「从 IR 生成视图」，绝不反向修改 IR。
若场景尚无 prose，则渲染器输出结构占位（stub），而非空文本 ——
这样 IR 与文本之间的映射始终可追溯。
"""

from __future__ import annotations

from ..ir.models import NarrativeIR, SceneNode


def _scene_heading(idx: int, scene: SceneNode, show_meta: bool) -> str:
    parts = [f"第 {idx} 章  {scene.title}"]
    if show_meta:
        parts.append(
            f"<!-- id={scene.id} 视角={scene.focalizer} "
            f"聚焦={scene.focalization.value} 时间=第{scene.fabula_time.day}天 "
            f"话语序={scene.sjuzhet_index} 频率={scene.frequency.value} "
            f"价值={scene.value} {scene.value_charge_start}→{scene.value_charge_end} "
            f"结果={scene.outcome.value} -->"
        )
    return "\n".join(parts)


def _stub(scene: SceneNode) -> str:
    return (
        f"（待写）目标：{scene.goal}\n"
        f"（待写）冲突：{scene.conflict}\n"
        f"（待写）转折：{scene.turning_point}\n"
    )


def render_text(
    ir: NarrativeIR,
    *,
    show_meta: bool = False,
    chronological: bool = False,
    stub_missing: bool = True,
    force_prose: bool = False,
) -> str:
    """渲染为小说/网文正文。

    chronological=True 时按故事时间排序（用于检查时序倒错的效果）。

    **网文正文默认不出**（`force_prose=False` 且在 `policy.PROSE_BLOCKED_MEDIA`
    里时抛 `PolicyError`）。依据 F6：起点 / 番茄 / 晋江 一致禁止 AI 直出正文，
    同一个 Keel 做网文是违规工具、做剧本是合规工具。
    这是**策略闸门不是能力删除** —— 显式 `force_prose=True` 可以放行，
    但放行的同时必须把风险告知作者。详见 `keel/policy.py`。
    """
    from ..policy import PolicyError, blocked_reason

    reason = blocked_reason(ir.medium)
    if reason and not force_prose:
        raise PolicyError(reason)

    scenes = ir.chronological_scenes() if chronological else ir.ordered_scenes()
    lines: list[str] = [f"# {ir.title}", ""]

    for i, s in enumerate(scenes, 1):
        lines.append(_scene_heading(i, s, show_meta))
        lines.append("")
        if s.prose:
            lines.append(s.prose.strip())
        elif stub_missing:
            lines.append(_stub(s).strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_outline(ir: NarrativeIR) -> str:
    """渲染为大纲（供人工确认 —— 人机协作位点在 IR 层，不在文本层）。"""
    lines = [
        f"# {ir.title}",
        "",
        f"**Logline**  {ir.commitment.logline}",
        f"**前提**     {ir.commitment.premise}",
        f"**控制理念** {ir.commitment.controlling_idea}",
        f"**弧线**     {ir.commitment.arc_shape.value}",
        f"**结局锚点** {ir.commitment.ending_anchor}",
        f"**媒介**     {ir.medium.value}",
        "",
        "## 作者承诺",
        "",
    ]
    for c in ir.commitment.commitments:
        mark = "✓" if c.satisfied else "○"
        lines.append(f"- {mark} `{c.kind}` {c.statement}")
    lines += ["", "## 场景表", ""]
    lines.append("| # | 场景 | 视角 | 价值 | 转折 | 结果 | 情绪 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, s in enumerate(ir.ordered_scenes(), 1):
        lines.append(
            f"| {i} | {s.title} | {s.focalizer} | {s.value} "
            f"{s.value_charge_start}→{s.value_charge_end} | {s.turning_point} "
            f"| {s.outcome.value} | {s.emotion:+.2f} |"
        )
    return "\n".join(lines) + "\n"
