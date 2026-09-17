"""Ink 脚本渲染器（inkle/ink）。

为什么选 Ink 做互动小说后端：
    - 内容与呈现分离：一份 .ink 同时驱动 3D 游戏和纯文本网页
    - 语法极简，LLM 可直接输出，也可机器生成
    - 有成熟的编译链：inklecate / inkjs → JSON runtime

导出策略（对应 1.5 阶段）：
    单线骨架 + 预留分支点。分支点由 IR 的 is_branch_point 与 storylet 决定。
    Ink 的 `->` 跳转与 `*` 选择语法使「Waypoint 骨架 + Storylet 池」
    可以自然映射：knot = waypoint，stitch = storylet 变体。
"""

from __future__ import annotations

from ..ir.models import NarrativeIR, SceneNode


def _safe(name: str) -> str:
    """Ink 标识符只允许字母数字下划线。"""
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
    if out and out[0].isdigit():
        out = "s_" + out
    return out


def _ink_text(scene: SceneNode) -> str:
    if scene.prose:
        body = scene.prose.strip()
        # Ink 中 `*` 与 `->` 是保留符号，正文里要转义
        body = body.replace("->", "\\->")
        lines = [l for l in body.split("\n") if l.strip()]
        return "\n".join(lines)
    return f"（待写）{scene.goal} / {scene.conflict} / {scene.turning_point}"


def render_ink(ir: NarrativeIR, *, emit_choices: bool = True) -> str:
    """渲染为 Ink 脚本。"""
    scenes = ir.ordered_scenes()
    lines: list[str] = []

    # --- 全局变量（品质） ---
    lines.append("// ==== Loom 生成：全局品质 ====")
    for q, v in sorted(ir.qualities.items()):
        lines.append(f"VAR {_safe(q)} = {_ink_literal(v)}")
    if not ir.qualities:
        lines.append("// （无已声明品质 —— 1.5 阶段应引入 quality 概念）")
    lines.append("")

    # --- 故事元信息 ---
    lines.append("// ==== 元信息 ====")
    lines.append(f"// Logline: {ir.commitment.logline}")
    lines.append(f"// Premise: {ir.commitment.premise}")
    lines.append(f"// Arc: {ir.commitment.arc_shape.value}")
    lines.append("")

    # --- 场景 knots ---
    for i, s in enumerate(scenes):
        lines.append(f"// ==== 场景 {i + 1}：{s.title} ====")
        lines.append(f"// 视角={s.focalizer} 价值={s.value} "
                     f"{s.value_charge_start}→{s.value_charge_end} 结果={s.outcome.value}")
        lines.append(f"== {_safe(s.id)} ==")
        lines.append(_ink_text(s))
        lines.append("")

        if emit_choices and s.is_branch_point:
            lines.append("// 分支点 —— 由 storylet 池展开")
            options = _branch_options(ir, s)
            if options:
                for opt in options:
                    lines.append(f"* [{opt['text']}] -> {_safe(opt['target'])}")
            else:
                lines.append("// （未挂载 storylet；保留一个占位选项）")
                lines.append(f"* [继续] -> {_safe(_next_id(scenes, i))}")
            lines.append("")
        else:
            nxt = _next_id(scenes, i)
            lines.append(f"-> {_safe(nxt)}" if nxt else "-> END")
            lines.append("")

    # --- storylet 池（QBN / salience） ---
    if ir.storylets:
        lines.append("// ==== Storylet 池（QBN：玩家在合法项中选择）====")
        lines.append("// 硬不变量：永远不要给玩家零个选项，必须保留一张可重复的底牌。")
        lines.append("")
        for st in ir.storylets:
            lines.append(f"== {_safe(st.id)} ==")
            lines.append(f"// salience={st.salience} advances={st.advances_waypoint}")
            if st.preconditions:
                conds = " and ".join(_cond_ink(c) for c in st.preconditions)
                lines.append(f"{{ {conds}:")
            lines.append(st.content)
            if st.choices:
                for ch in st.choices:
                    lines.append(f"* [{ch.text}] -> {_safe(st.advances_waypoint or 'END')}")
            else:
                lines.append(f"-> {_safe(st.advances_waypoint or 'END')}")
            if st.preconditions:
                lines.append("}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _ink_literal(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return f'"{v}"'


def _cond_ink(c) -> str:
    op = {"==": "==", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<="}.get(c.op)
    if op:
        return f"{_safe(c.quality)} {op} {_ink_literal(c.value)}"
    return "true"


def _next_id(scenes: list[SceneNode], i: int) -> str | None:
    return scenes[i + 1].id if i + 1 < len(scenes) else None


def _branch_options(ir: NarrativeIR, scene: SceneNode) -> list[dict]:
    out = []
    for sid in scene.storylet_ids:
        st = next((x for x in ir.storylets if x.id == sid), None)
        if st:
            out.append(
                {
                    "text": st.content.strip().split("\n")[0][:24] or st.id,
                    "target": st.advances_waypoint or st.id,
                }
            )
    return out
