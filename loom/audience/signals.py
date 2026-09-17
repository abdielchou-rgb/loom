"""观众信号抽取 —— 全部确定性、可检查。

这是整个观众模拟的地基，也是它区别于「让 LLM 猜观众会不会喜欢」的地方。

原则：**能被算出来的，绝不交给模型猜。**
模型只负责它真正擅长的部分 —— 把数值翻译成「人话」（观众的原话、抱怨、
高光点）。数值本身必须是可复现、可审计、可回归测试的。

每场的信号：
    flips            本场是否发生价值翻转（McKee）
    has_hook         本场是否有钩子（翻转 / 新谜题 / 分支点）
    open_enigmas     截至本场仍悬空未解的谜题数（好奇心张力）
    new_enigmas      本场新埋的谜题数
    resolved_enigmas 本场回收的谜题数（「给到」的密度）
    info_density     本场承载的谜题动作总数（过载检测）
    slop_score       本场文字的「去 AI 味得分」0-100
    emotion_delta    与前一场的情绪落差（起伏感）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..audit.anti_slop import scan_slop
from ..ir.models import NarrativeIR


@dataclass
class SceneSignals:
    scene_id: str
    index: int
    position: float
    flips: bool
    outcome: str
    emotion: float
    emotion_delta: float
    slop_score: int
    new_enigmas: int
    resolved_enigmas: int
    open_enigmas: int
    info_density: int
    has_hook: bool
    word_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "index": self.index,
            "position": round(self.position, 3),
            "flips": self.flips,
            "outcome": self.outcome,
            "emotion": self.emotion,
            "emotion_delta": round(self.emotion_delta, 3),
            "slop_score": self.slop_score,
            "new_enigmas": self.new_enigmas,
            "resolved_enigmas": self.resolved_enigmas,
            "open_enigmas": self.open_enigmas,
            "info_density": self.info_density,
            "has_hook": self.has_hook,
            "word_count": self.word_count,
        }


def scene_signals(ir: NarrativeIR) -> list[SceneSignals]:
    """按话语顺序逐场抽取信号。"""
    scenes = ir.ordered_scenes()
    n = len(scenes)
    if n == 0:
        return []

    planted: dict[str, int] = {}
    resolved: dict[str, int] = {}
    for e in ir.enigmas:
        if e.planted_at_scene:
            planted[e.planted_at_scene] = planted.get(e.planted_at_scene, 0) + 1
        if e.resolved_at_scene:
            resolved[e.resolved_at_scene] = resolved.get(e.resolved_at_scene, 0) + 1

    out: list[SceneSignals] = []
    open_count = 0
    prev_emotion: float | None = None

    for i, s in enumerate(scenes):
        new_e = planted.get(s.id, 0)
        res_e = resolved.get(s.id, 0)
        # 本场先解后埋：净开放数
        open_count = max(0, open_count + new_e - res_e)
        density = new_e + res_e
        slop = scan_slop(s.prose or "", scene_id=s.id).score
        delta = 0.0 if prev_emotion is None else s.emotion - prev_emotion
        out.append(
            SceneSignals(
                scene_id=s.id,
                index=i,
                position=0.0 if n == 1 else i / (n - 1),
                flips=s.value_flips,
                outcome=s.outcome.value,
                emotion=s.emotion,
                emotion_delta=delta,
                slop_score=slop,
                new_enigmas=new_e,
                resolved_enigmas=res_e,
                open_enigmas=open_count,
                info_density=density,
                has_hook=s.value_flips or new_e > 0 or s.is_branch_point,
                word_count=len(s.prose or ""),
            )
        )
        prev_emotion = s.emotion
    return out


def ir_signals(ir: NarrativeIR) -> dict[str, Any]:
    """整部作品的聚合信号。既是模拟器的输入，也是 LLM 判断的输入。"""
    ss = scene_signals(ir)
    n = len(ss) or 1
    scenes = ir.ordered_scenes()

    outcomes = [s.outcome.value for s in scenes]
    distinct_outcomes = len(set(outcomes))
    # 结果类型的最大可能分布数（4 种：yes / yes_but / no / no_and）
    outcome_variety = (distinct_outcomes - 1) / 3.0 if n > 1 else 0.0

    slop_avg = sum(s.slop_score for s in ss) / n if ss else 100.0

    enigma_total = len(ir.enigmas) or 1
    open_ratio = sum(1 for e in ir.enigmas if not e.resolved_at_scene) / enigma_total

    # 中段的悬念持续性 —— 这才是「抓不抓人」的指标。
    # 注意不能用全局 open_ratio：一个把所有线都收干净的结局是**完成度**，
    # 不是缺陷。用全局比例会把收得漂亮的作品判成「太顺」。
    mid = ss[1:-1] if len(ss) > 2 else ss
    mid_open_ratio = (
        sum(1 for s in mid if s.open_enigmas > 0) / len(mid) if mid else 0.0
    )

    return {
        "scene_count": n,
        "value_flip_ratio": sum(1 for s in ss if s.flips) / n,
        "hook_ratio": sum(1 for s in ss if s.has_hook) / n,
        "outcome_variety": outcome_variety,
        "distinct_outcomes": distinct_outcomes,
        "open_enigma_ratio": open_ratio,
        "mid_open_ratio": round(mid_open_ratio, 3),
        "enigma_count": len(ir.enigmas),
        "avg_info_density": sum(s.info_density for s in ss) / n,
        "max_info_density": max((s.info_density for s in ss), default=0),
        "slop_score": round(slop_avg, 1),
        "avg_emotion_delta": round(
            sum(abs(s.emotion_delta) for s in ss) / n, 3
        ),
        "word_count": ir.word_count(),
        "arc_shape": ir.commitment.arc_shape.value,
        "medium": ir.medium.value,
    }
