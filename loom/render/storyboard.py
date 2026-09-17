"""漫画分镜 JSON 渲染器。

背景：业界目前**没有标准的分镜 schema**（v2 调研确认的真空地带之一）。
本模块定义一套最小可用 schema，作为 IR 的第二个 renderer。

图像生成走外部模型（本系统不产出图像），分镜 JSON 只负责描述：
    镜头 / 角色 / 地点 / 情绪 / 台词 / 一致性锚点
每个 panel 携带 character_ref，供下游做角色一致性（参考图 / LoRA / 共享种子）。
"""

from __future__ import annotations

import json

from ..ir.models import NarrativeIR, SceneNode

# 镜头语言枚举（借 McCloud 的六种面板过渡 + 通用电影镜头）
SHOT_TYPES = {
    "establishing": "远景/建立镜头",
    "wide": "全景",
    "medium": "中景",
    "close_up": "特写",
    "extreme_close_up": "大特写",
    "over_shoulder": "过肩",
    "pov": "主观视角",
    "insert": "插入镜头",
}

# McCloud《Understanding Comics》的六种面板过渡
PANEL_TRANSITIONS = {
    "moment_to_moment": "瞬间到瞬间",
    "action_to_action": "动作到动作",
    "subject_to_subject": "主体到主体",
    "scene_to_scene": "场景到场景",
    "aspect_to_aspect": "方面到方面",
    "non_sequitur": "非逻辑跳跃",
}


def _shots_for(scene: SceneNode) -> list[str]:
    """按场景结构推断镜头序列。情绪强度越高，特写越多。"""
    shots = ["establishing", "wide"]
    if scene.conflict:
        shots.append("medium")
    if abs(scene.emotion) > 0.5 or scene.value_flips:
        shots.extend(["close_up", "extreme_close_up"])
    shots.append("medium")
    if scene.outcome.value in ("no_and", "no"):
        shots.append("close_up")
    return shots


def _transition_for(scene: SceneNode, index: int, total: int) -> str:
    if index == 0:
        return "scene_to_scene"
    if scene.value_flips:
        return "action_to_action"
    if scene.frequency.value == "iterative":
        return "aspect_to_aspect"
    return "subject_to_subject"


def build_storyboard(ir: NarrativeIR) -> dict:
    """构建分镜 JSON。"""
    scenes = ir.ordered_scenes()
    total = len(scenes)
    panels: list[dict] = []
    pid = 0

    for si, scene in enumerate(scenes):
        shots = _shots_for(scene)
        for k, shot in enumerate(shots):
            pid += 1
            chars = [
                cid for cid in scene.entities if cid in ir.characters.characters
            ]
            panel: dict = {
                "id": f"p{pid:04d}",
                "scene_id": scene.id,
                "panel_index": pid,
                "shot": shot,
                "shot_label": SHOT_TYPES[shot],
                "transition": (
                    _transition_for(scene, si, total) if k == 0 else "action_to_action"
                ),
                "location": scene.location,
                "focalizer": scene.focalizer,
                "characters": chars,
                "character_ref": {
                    cid: {
                        "entity_id": cid,
                        "name": ir.characters.characters[cid].name,
                        "consistency_key": f"char_{cid}",
                        "sheet_hint": (
                            f"{ir.characters.characters[cid].name} 的角色设定图："
                            f"固定发型、服装、体态；本镜头保持一致性"
                        ),
                    }
                    for cid in chars
                },
                "emotion": round(scene.emotion, 3),
                "value_charge": f"{scene.value_charge_start}→{scene.value_charge_end}",
                "value": scene.value,
                "dialogue": [],
                "caption": "",
                "prompt_seed": None,
            }
            if k == len(shots) - 1 and scene.prose:
                panel["caption"] = scene.prose.strip().split("\n")[0][:80]
            elif k == 1:
                panel["caption"] = scene.goal
            panels.append(panel)

    return {
        "schema": "loom.storyboard/0.1",
        "title": ir.title,
        "medium": "comic",
        "style_tokens": ir.tags or ["默认风格"],
        "character_sheets": [
            {
                "entity_id": c.id,
                "name": c.name,
                "consistency_key": f"char_{c.id}",
                "description": f"{c.name}：{c.arc_from} → {c.arc_to}。缺陷：{c.flaw}",
                "voice": c.voice,
            }
            for c in ir.characters.characters.values()
        ],
        "panels": panels,
        "meta": {
            "panel_count": len(panels),
            "scene_count": len(scenes),
            "note": (
                "本 schema 为 Loom 自定义。行业目前无标准分镜格式。"
                "图像生成走外部模型；character_ref.consistency_key 用于绑定"
                "参考图 / LoRA / 共享种子，以保证角色一致性。"
            ),
        },
    }


def render_storyboard(ir: NarrativeIR, indent: int = 2) -> str:
    return json.dumps(build_storyboard(ir), ensure_ascii=False, indent=indent)
