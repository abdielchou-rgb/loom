"""Ren'Py 脚本渲染器（galgame / 视觉小说）。

为什么选 Ren'Py：MIT 许可、5k+ stars、内建 Python 可直接调 LLM API，
一键出 Windows / macOS / Linux / Android / iOS / Web。

galgame 的结构要求（与线性小说不同）：
    共通线 → 個別線（角色路线）→ 锁定路线 → True End
    好感度 flag、路线解锁条件、立绘与背景资产清单

本渲染器把这些从 IR 派生出来：Character 的 goals + storylet 的 qualities。
"""

from __future__ import annotations

from ..ir.models import NarrativeIR, SceneNode


def _safe(name: str) -> str:
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
    return out or "unnamed"


def _esc(text: str) -> str:
    """Ren'Py 字符串里双引号与反斜杠要转义。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def render_renpy(ir: NarrativeIR, *, include_assets: bool = True) -> str:
    scenes = ir.ordered_scenes()
    lines: list[str] = []

    lines.append("# ==== Loom 生成：Ren'Py 脚本 ====")
    lines.append(f"# {ir.title}")
    lines.append(f"# Logline: {ir.commitment.logline}")
    lines.append("#")
    lines.append("# 用法：把本文件放入 game/ 目录，配合 assets 清单准备立绘与背景。")
    lines.append("")

    # --- 角色定义 ---
    lines.append("# ---- 角色 ----")
    for c in ir.characters.characters.values():
        lines.append(
            f'define {_safe(c.id)} = Character("{_esc(c.name)}", '
            f'who_color="#c8a2c8")'
        )
    lines.append("")

    # --- 好感度与 flag ---
    lines.append("# ---- 好感度与 flag（galgame 状态机） ----")
    for c in ir.characters.characters.values():
        lines.append(f"default affection_{_safe(c.id)} = 0")
    for q, v in sorted(ir.qualities.items()):
        lines.append(f"default {_safe(q)} = {_renpy_literal(v)}")
    if not ir.qualities:
        lines.append("# （尚无品质变量 —— 建议在 1.5 阶段引入）")
    lines.append("")

    # --- 场景 ---
    lines.append("label start:")
    lines.append("")
    for i, s in enumerate(scenes):
        lines.append(f"    # ---- {i + 1}. {s.title} ----")
        lines.append(
            f"    # 视角={s.focalizer} 聚焦={s.focalization.value} "
            f"价值={s.value}{s.value_charge_start}→{s.value_charge_end} "
            f"结果={s.outcome.value}"
        )
        if s.location:
            lines.append(f'    scene bg {_safe(s.location)} with dissolve')
        for cid in s.entities:
            if cid in ir.characters.characters:
                mood = "happy" if s.emotion > 0.3 else ("sad" if s.emotion < -0.3 else "normal")
                lines.append(f'    show {_safe(cid)} {mood} at center')
        lines.append("")

        if s.prose:
            for para in [p.strip() for p in s.prose.split("\n") if p.strip()]:
                lines.append(f'    "{_esc(para)}"')
        else:
            lines.append(f'    # （待写）{_esc(s.goal)}')
            lines.append(f'    # （待写）{_esc(s.conflict)}')
            lines.append(f'    # （待写）{_esc(s.turning_point)}')
        lines.append("")

        if s.is_branch_point:
            opts = _renpy_options(ir, s)
            if opts:
                lines.append("    menu:")
                for label, target, effect in opts:
                    lines.append(f'        "{_esc(label)}":')
                    if effect:
                        lines.append(f"            {effect}")
                    lines.append(f"            jump {_safe(target)}")
            else:
                lines.append("    menu:")
                lines.append('        "继续":')
                lines.append(f"            jump {_safe(_next(scenes, i))}")
            lines.append("")
        elif s.is_paywall_gate:
            lines.append("    # 【付费卡点】此处为免费/付费分界")
            lines.append(f"    jump {_safe(_next(scenes, i))}")
            lines.append("")

    lines.append("    return")
    lines.append("")

    # --- 路线图 ---
    lines.append("# ---- 路线图（共通线 → 個別線 → True End） ----")
    lines.append("#")
    for c in ir.characters.characters.values():
        goals = "；".join(g.description for g in c.goals) or "（未定义目标）"
        lines.append(
            f"# [{c.name}] 好感度 >= 60 解锁個別線 | 目标：{goals}"
        )
    lines.append("# True End 条件：所有個別線达成后解锁")
    lines.append("")

    if include_assets:
        lines.append("# ---- 资产清单 ----")
        locs = sorted({s.location for s in scenes if s.location})
        lines.append(f"# 背景 ({len(locs)}): " + ", ".join(f"bg {_safe(l)}" for l in locs))
        chars = sorted(ir.characters.characters)
        lines.append(
            f"# 立绘 ({len(chars)} × 3 表情): "
            + ", ".join(f"{_safe(c)} [normal/happy/sad]" for c in chars)
        )
        lines.append("# 注意：AI 配音对国乙用户是雷点；真人配音需在资产阶段规划。")

    return "\n".join(lines).rstrip() + "\n"


def _renpy_literal(v: object) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return str(v)
    return f'"{v}"'


def _next(scenes: list[SceneNode], i: int) -> str:
    return scenes[i + 1].id if i + 1 < len(scenes) else "end"


def _renpy_options(ir: NarrativeIR, scene: SceneNode) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for sid in scene.storylet_ids:
        st = next((x for x in ir.storylets if x.id == sid), None)
        if not st:
            continue
        label = st.content.strip().split("\n")[0][:30] or st.id
        effect = ""
        if st.effects:
            parts = []
            for e in st.effects:
                q = _safe(e.quality)
                if e.op == "add":
                    parts.append(f"${q} += {e.value}")
                elif e.op == "sub":
                    parts.append(f"${q} -= {e.value}")
                else:
                    parts.append(f"${q} = {_renpy_literal(e.value)}")
            effect = "\n            ".join(parts)
        out.append((label, st.advances_waypoint or st.id, effect))
    return out
