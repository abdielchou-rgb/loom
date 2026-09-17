"""显式状态转移语义校验器（P2 · 显式状态转移语义）。

实现 ConWriter (EMNLP 2026, arXiv 2608.05169) 的 Pre/Post/Forbidden
符号化验证，叠加 Todorov (1977) 的叙事转化态追踪。

方法论出处：
  * Todorov (1977) *The Poetics of Prose* —— 叙事 = 一连串「平衡态 →
    失衡 → 新平衡」的转化（transformation）。每个场景通过 `StateDelta`
    把实体从 `before` 态推到 `after` 态。本校验器沿话语顺序（sjuzhet）
    维护「每实体的累计状态」，相当于把 Todorov 的稳态序列化，才能跨场景
    追问「这个状态现在还成立吗」—— 这正是单场景校验器做不到的。
  * ConWriter (Li et al., EMNLP 2026, arXiv:2608.05169) —— 用
    (Precondition, Postcondition, Forbidden) 三元组做符号化一致性验证：
    Pre = 本事件成立前世界必须满足的条件；Post = 事件后必然成立；
    Forbidden = 事件后**绝不可成立**的状态。本校验器把 `forbidden` 显式
    落成 IR 字段（`StateDelta.forbidden`），并对每条 Forbidden 检查
    「后续场景是否又把该实体放回了被禁状态」。

两条判据（都是硬结构错误，ERROR）：

  1. Forbidden-state violation（禁忌态复现）
     某场景 M 的 delta 用 `forbidden=["alive"]` 终结了实体 X 的某个正向态
     （典型：死亡）。若后续场景 N (>M) 又把 X 当作聚焦者 (focalizer) 或
     出场实体 (entities / 参与者) 引入 —— 即把 X 重新放回「在场 / 存活」
     的角色 —— 则触发 ERROR，并点名**确立禁忌态的那一场 M**（让用户知道
     去改哪一场）。若 forbidden 写成 `attribute=value` 形式，则检查后续
     delta 是否把该属性重新置回该值（复活式回写）。

  2. Precondition violation（前置条件不满足）
     若某场景挂接的情节事件（plot.events[ev].scene_id == 本场景）带有
     Precondition(kind="attribute")，而该属性在**上一场景结束时**的累计
     状态并未满足，则触发 ERROR，并点名最后一次确立冲突态的那一场
     （即「把世界设成与前置条件相悖」的那一场）。

SKIPPED ≠ PASS：若 IR 根本没有 state_deltas / 没有 forbidden / 没有事件
前置条件，本校验器返回 []（不产出 Finding），而非伪造一条 PASS。
"""

from __future__ import annotations

from typing import Any

from ..ir.enums import Severity
from ..ir.models import NarrativeIR, StateDelta
from .base import Finding, register


def _parse_forbidden(entry: str) -> tuple[str, str | None]:
    """把 forbidden 条目拆成 (attribute, value?)。

    "alive"        -> ("alive", None)      # 纯禁忌态（在场 / 存活）
    "status=alive" -> ("status", "alive")  # 属性值禁忌
    """
    entry = entry.strip()
    if "=" in entry:
        attr, val = entry.split("=", 1)
        return attr.strip(), val.strip()
    return entry, None


def _presence_violates(scene: Any, eid: str) -> bool:
    """实体 eid 是否在本场景被重新引入为在场角色（聚焦者 / 出场实体）。

    单独抽成谓词，便于变异测试：把它翻成永远返回 False，
    禁忌态复现检查即「永不触发」，反例测试必须随之变红。
    """
    return scene.focalizer == eid or eid in scene.entities


@register("state_transition_integrity")
def state_transition_integrity(ir: NarrativeIR) -> list[Finding]:
    """显式状态转移语义：Forbidden 复现 + Precondition 不满足。

    见模块 docstring 的方法论出处（Todorov 1977; ConWriter, EMNLP 2026）。
    """
    out: list[Finding] = []

    # 每实体累计状态：entity -> {attribute: value}（来自各 delta 的 after）
    active: dict[str, dict[str, Any]] = {}
    # 禁忌态：entity -> [(attribute, value?, established_scene_id)]
    forbidden: dict[str, list[tuple[str, str | None, str]]] = {}
    # 最后确立某 (entity, attribute) 态的场景（用于 Precondition 反向定位）
    last_set: dict[tuple[str, str], str] = {}

    for s in ir.ordered_scenes():
        # ---- 1. Forbidden 复现（在场 / 存活型，无 value）----
        # 先对「本场景之前已确立」的禁忌态做检查：本场景把实体重新引入为
        # 聚焦者或出场实体，即把它重新放回被禁的在场态。
        for eid, flist in forbidden.items():
            for attr, val, estab in flist:
                if val is not None:
                    continue  # 属性值型禁忌在步骤 3 的回写时检查
                if _presence_violates(s, eid):
                    out.append(
                        Finding(
                            code="state_transition_integrity",
                            severity=Severity.ERROR,
                            scene_id=s.id,
                            entity_id=eid,
                            message=(
                                f"实体「{eid}」在场景 {s.id} 以被禁的「{attr}」状态复现"
                                f"（作为聚焦者 / 出场实体出现），但该禁忌态由场景 {estab} 确立"
                                f"（例如死亡后不应再作为在场角色出现）。请修改场景 {estab} "
                                f"或 {s.id}。"
                            ),
                            suggestion=(
                                f"要么在 {estab} 撤销该 forbidden 设定，"
                                f"要么让 {s.id} 不再以 {eid} 为聚焦者 / 出场实体"
                            ),
                            evidence={
                                "forbidden_set_at": estab,
                                "entity_id": eid,
                                "attribute": attr,
                            },
                        )
                    )

        # ---- 2. Precondition 不满足 ----
        # 本场景挂接的情节事件，其 attribute 型前置条件须由上一场景结束时的
        # 累计状态满足。
        for ev in ir.plot.events.values():
            if ev.scene_id != s.id:
                continue
            for pc in ev.preconditions:
                if pc.kind != "attribute":
                    continue
                cur = active.get(pc.target, {}).get(pc.attribute)
                if cur != pc.value:
                    estab = last_set.get((pc.target, pc.attribute))
                    out.append(
                        Finding(
                            code="state_transition_integrity",
                            severity=Severity.ERROR,
                            scene_id=s.id,
                            entity_id=pc.target,
                            message=(
                                f"场景 {s.id} 的事件「{ev.id}」要求前置条件 "
                                f"{pc.target}.{pc.attribute}=={pc.value!r}，"
                                f"但上一场景结束时该属性为 {cur!r}"
                                + (
                                    f"（冲突态由场景 {estab} 确立）"
                                    if estab
                                    else "（此前从未确立过该属性）"
                                )
                            ),
                            suggestion=(
                                "在场景 "
                                + (estab or "此前")
                                + " 修正状态转移，或修正该事件的前置条件"
                            ),
                            evidence={
                                "precondition": {
                                    "target": pc.target,
                                    "attribute": pc.attribute,
                                    "expected": pc.value,
                                    "actual": cur,
                                },
                                "conflict_set_at": estab,
                                "scene": s.id,
                            },
                        )
                    )

        # ---- 3. 应用本场景的 delta，推进累计状态 / 登记禁忌态 ----
        for d in s.state_deltas:
            # 3a. 属性值型禁忌的回写：本 delta 把属性重新置回被禁的值
            for attr, val, estab in forbidden.get(d.entity_id, []):
                if val is not None and attr == d.attribute and d.after == val:
                    out.append(
                        Finding(
                            code="state_transition_integrity",
                            severity=Severity.ERROR,
                            scene_id=s.id,
                            entity_id=d.entity_id,
                            message=(
                                f"实体「{d.entity_id}」在场景 {s.id} 被重新置回被禁状态 "
                                f"{attr}={val!r}（禁忌态由场景 {estab} 确立）"
                            ),
                            suggestion=f"场景 {estab} 已禁止该状态，{s.id} 不应复活它",
                            evidence={
                                "forbidden_set_at": estab,
                                "entity_id": d.entity_id,
                                "attribute": attr,
                            },
                        )
                    )
            active.setdefault(d.entity_id, {})[d.attribute] = d.after
            last_set[(d.entity_id, d.attribute)] = s.id
            if d.forbidden:
                for entry in d.forbidden:
                    a, v = _parse_forbidden(entry)
                    forbidden.setdefault(d.entity_id, []).append((a, v, s.id))

    return out
