"""Fountain 剧本渲染器（fountain.io 规范）。

为什么选 Fountain：它是剧本交换的事实标准，纯文本、无专有格式，
screenplain / afterwriting 等现成工具可转 PDF / FDX / HTML。
"""

from __future__ import annotations

import re

from ..ir.enums import EntityKind, Focalization, Frequency
from ..ir.medium_craft import split_slugline
from ..ir.models import NarrativeIR, SceneNode

_CJK = re.compile(r"[\u4e00-\u9fff]")

def _location_of(scene: SceneNode, ir: NarrativeIR) -> str:
    """场景地点：优先场景卡，退化到出场实体里的 location 类，再退化到显式未定。

    「UNKNOWN」是坏答案：它让读者以为渲染器坏了，而实际是**上游没给**。
    写「未定地点」才把责任指向该负责的那一层。
    """
    if scene.location:
        return scene.location
    for cid in scene.entities:
        ent = ir.bible.entities.get(cid)
        if ent is not None and ent.kind is EntityKind.LOCATION:
            return ent.name
    return ""


def _slugline(scene: SceneNode, ir: NarrativeIR) -> str:
    ie, place = split_slugline(_location_of(scene, ir))
    if not place:
        place = "未定地点"
    tod = _time_of_day(scene)
    if _CJK.search(place):
        # 没有时间标记就只写地点 —— 场景标题缺时间仍然合法，
        # 写上一个猜出来的「夜」才是缺陷。
        return f"{ie or '内/外景'}．{place}" + (f"．{tod}" if tod else "")
    head = {"内景": "INT.", "外景": "EXT."}.get(ie, "INT./EXT.")
    return f"{head} {place.upper()}" + (f" - {tod.upper()}" if tod else "")


def _time_of_day(scene: SceneNode) -> str:
    """场景的时间标记。拿不到就返回空串 —— 由调用方决定怎么显示。

    这里**曾经**写的是 `scene.fabula_time.day % 24`：把「故事内第几天」
    当成了「几点钟」。后果是 day=0/1/2 全被算成凌晨，于是**每一场都渲染成
    「夜」**。这不是渲染器偷懒，是把一个字段的语义读错了。

    修法不是换个更聪明的猜法，而是承认 IR 里本来就没有「钟点」这个字段：
    时间标记由结构层显式给出（`fabula_time.label`），没给就不写。
    宁可少一个时间标记，也不要给整部戏盖上一层假的夜色。
    """
    label = scene.fabula_time.label
    if label:
        return label
    if scene.fabula_time.is_flashback:
        return "闪回"
    return ""


def _speaker_name(ir: NarrativeIR, cid: str) -> str:
    ch = ir.characters.characters.get(cid)
    if ch:
        return ch.name.upper() if not _CJK.search(ch.name) else ch.name
    ent = ir.bible.entities.get(cid)
    return ent.name if ent else cid


def render_fountain(ir: NarrativeIR, *, include_notes: bool = True) -> str:
    """渲染为 Fountain 剧本。

    说明：本渲染器把场景的 `turning_point` / 价值转折写为 Fountain 注释
    （`[[ ]]`），这样剧本在 Final Draft / Highland 里打开时，
    结构信息不丢失，但也不会污染可拍摄内容。
    """
    lines: list[str] = []
    lines.append(f"Title: {ir.title}")
    lines.append("Credit: 由 Keel 叙事编译器生成")
    lines.append(f"Draft date: {ir.commitment.arc_shape.value}")
    if include_notes:
        lines.append("")
        lines.append(f"[[Logline: {ir.commitment.logline}]]")
        lines.append(f"[[Premise: {ir.commitment.premise}]]")
    lines.append("")
    lines.append("====")
    lines.append("")

    for s in ir.ordered_scenes():
        lines.append(_slugline(s, ir))
        if include_notes:
            lines.append(
                f"[[id={s.id} 视角={s.focalizer} "
                f"聚焦={s.focalization.value} "
                f"价值={s.value}{s.value_charge_start}→{s.value_charge_end} "
                f"结果={s.outcome.value}]]"
            )
        lines.append("")

        if s.prose:
            for para in s.prose.strip().split("\n"):
                para = para.strip()
                if not para:
                    continue
                lines.append(para)
                lines.append("")
        else:
            lines.append(f"[[待写]] 目标：{s.goal}")
            lines.append(f"[[待写]] 冲突：{s.conflict}")
            lines.append(f"[[待写]] 转折：{s.turning_point}")
            lines.append("")

        if s.frequency is Frequency.REPETITIVE:
            lines.append("[[注意：本场为重复叙事（同一事件多次讲述）]]")
            lines.append("")
        if s.focalization is Focalization.EXTERNAL:
            lines.append("[[注意：外聚焦——只呈现可观察行为，不进意识]]")
            lines.append("")
        if s.is_paywall_gate:
            lines.append("[[付费卡点：本场为免费/付费分界]]")
            lines.append("")

        lines.append("====")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
