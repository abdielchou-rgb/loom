"""互动叙事分支一致性校验器（P6 · 2.0 互动叙事 —— 分支一致性校验器）。

针对 Ink / Ren'Py 这类互动小说：同一份 IR 可以分支。本校验器检查
**从同一故事节点分叉出的两条分支**，其建立的累计实体状态不得互相矛盾。

方法论出处：
  * 互动叙事的「分支一致性」(branch consistency) —— Emily Short《Beyond
    Branching》(2016) 强调：分支不是孤立的平行宇宙，而是从同一故事点
    长出的可能世界。两条分支对同一实体在同一故事点设定了**互斥**状态
    （如分支 A 让 X 活着、分支 B 让 X 死亡），意味着作者在两个世界里
    写了两套互相矛盾的「事实」，读者若走完两条线会抓到吃书。
  * 承诺层（L3, Egri 控制理念）的可达性：作者承诺某主题/结局必须成立。
    若承诺在分支 A 中被满足，但其前提在分支 B 中被否定，则该承诺
    在「分支 B 这一条真实可走的路径」上被破坏 —— 这违背了承诺层
    的不变量（commitment 是防漂离论点的硬约束，见 ir/models.py::CommitmentLayer）。

两条判据（都是 ERROR 级硬结构错误）：

  1. 实体属性矛盾（entity-attribute contradiction）
     给定两条共享同一分叉点（parent_point）的分支，对每个「两分支都设定了的」
     实体属性 (entity_id, attribute)，若两端取值互斥（如 alive ↔ dead、
     true ↔ false），则报 ERROR，点名实体、属性与两条分支。

  2. 承诺前提被否定（commitment premise negation）
     若某承诺 c 在分支 A 的 satisfied_commitments 中，却在分支 B 的
     negated_commitments 中（反之亦然），报 ERROR：该承诺在一条可走路径上
     被满足、在另一条上其前提被推翻。

SKIPPED ≠ PASS（铁律）：本校验器需要 IR 提供分支结构。由于 P6 阶段
NarrativeIR 尚未正式加入 `branches` 字段（models.py 为共享契约、不可改），
校验器**防御性地**读取 `getattr(ir, "branches", None)`：
  - 若该属性不存在或为空 → 返回 []（SKIPPED，不是伪造的 PASS）。
  - 未来 NarrativeIR 一旦加入 `branches` 字段，本读取逻辑自动生效，无需改动。
因此「没有分支结构」在今天的常见 IR 上是预期行为，校验器静默返回 []
（什么都不测），而非假装一切正常。
"""

from __future__ import annotations

from typing import Any

from ..ir.base import LoomModel
from ..ir.enums import Severity
from ..ir.models import NarrativeIR
from .base import Finding, register


# ---------------------------------------------------------------------------
# 分支结构（只读，不改 models.py）
# ---------------------------------------------------------------------------


class Branch(LoomModel):
    """一条从某个故事点分叉出的分支（可能世界）的累计状态快照。

    这是**本校验器自带的只读结构**，不写入共享的 `models.py`。
    它通过 `getattr(ir, "branches", None)` 被读到：
    未来 `NarrativeIR` 正式加入 `branches` 字段后本类即成为该字段的值类型，
    读取逻辑无需改动（向后兼容）。
    """

    id: str
    #: 该分支从哪个故事点分叉。None = 隐式根节点（所有根分支共享同一个祖先）。
    parent_point: str | None = None
    #: entity_id -> {attribute: value}：本分支确立的累计实体状态。
    entity_states: dict[str, dict[str, Any]] = {}
    #: 本分支满足的 L3 承诺 id 列表。
    satisfied_commitments: list[str] = []
    #: 本分支**否定**其前提的 L3 承诺 id 列表。
    negated_commitments: list[str] = []


def attach_branches(ir: NarrativeIR, branches: list[Branch | dict]) -> NarrativeIR:
    """把分支结构挂到 IR 上（P6 过渡期用法）。

    因为 `NarrativeIR` 用 `extra="forbid"`，不能直接 `ir.branches = ...`
    （会触发 ValidationError）。这里用 `object.__setattr__` 绕过字段校验，
    把分支临时挂在实例上，供 `branch_consistency` 用 `getattr` 读出。
    这是一个**过渡钩子**：等 `branches` 成为 `NarrativeIR` 的正式字段后，
    这层绕行即可删除，校验器读取逻辑不变。
    """
    object.__setattr__(ir, "branches", branches)
    return ir


# ---------------------------------------------------------------------------
# 矛盾判定
# ---------------------------------------------------------------------------


#: 互斥值对（规范化小写比较）。同一 (entity, attribute) 被两分支设为
#: 属于同一 frozenset 的两个不同值 → 逻辑矛盾。
_CONTRADICTORY_PAIRS = frozenset(
    {
        frozenset({"alive", "dead"}),
        frozenset({"living", "dead"}),
        frozenset({"true", "false"}),
        frozenset({"yes", "no"}),
        frozenset({"present", "absent"}),
        frozenset({"open", "closed"}),
        frozenset({"free", "captured"}),
        frozenset({"safe", "danger"}),
        frozenset({"win", "lose"}),
        frozenset({"loyal", "traitor"}),
        frozenset({"innocent", "guilty"}),
    }
)


def _norm(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip().lower()


def _contradictory(a: Any, b: Any) -> bool:
    """两值是否互斥（互否）。

    单独抽出便于变异测试：把它翻成永远返回 False，矛盾检测即「永不触发」，
    反例测试必须随之变红。
    """
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return False
    return frozenset({na, nb}) in _CONTRADICTORY_PAIRS


def _coerce(b: Any) -> Branch:
    if isinstance(b, Branch):
        return b
    if isinstance(b, dict):
        return Branch.model_validate(b)
    raise TypeError(f"branch 必须是 Branch 或 dict，收到 {type(b).__name__}")


# ---------------------------------------------------------------------------
# Finding 构造
# ---------------------------------------------------------------------------


def _entity_contradiction(
    a: Branch, b: Branch, eid: str, attr: str, va: Any, vb: Any
) -> Finding:
    return Finding(
        code="branch_consistency",
        severity=Severity.ERROR,
        entity_id=eid,
        message=(
            f"实体「{eid}」的属性「{attr}」在分支「{a.id}」为 {va!r}、"
            f"在分支「{b.id}」为 {vb!r}，二者矛盾"
            f"（如 alive 与 dead 不可同时成立）；"
            f"两条分支都从同一故事点 {a.parent_point or '根'} 分叉。"
        ),
        evidence={
            "branch_a": a.id,
            "branch_b": b.id,
            "attribute": attr,
            "entity_id": eid,
            "value_a": va,
            "value_b": vb,
            "parent_point": a.parent_point,
        },
    )


def _commitment_negation(
    satisfied: Branch, negated: Branch, cid: str
) -> Finding:
    return Finding(
        code="branch_consistency",
        severity=Severity.ERROR,
        message=(
            f"承诺「{cid}」在分支「{satisfied.id}」中被满足，"
            f"但其前提在分支「{negated.id}」中被否定；"
            f"该承诺在一条可走路径上成立、在另一条上被破坏。"
        ),
        evidence={
            "branch_a": satisfied.id,
            "branch_b": negated.id,
            "commitment_id": cid,
            "parent_point": satisfied.parent_point,
        },
    )


# ---------------------------------------------------------------------------
# 校验器主体
# ---------------------------------------------------------------------------


@register("branch_consistency")
def branch_consistency(ir: NarrativeIR) -> list[Finding]:
    """互动叙事分支一致性：实体属性矛盾 + 承诺前提被否定。

    见模块 docstring 的方法论出处（Emily Short 2016; Egri 控制理念 / L3 承诺层）。
    SKIPPED ≠ PASS：无 `branches` 属性或为空时返回 []，不伪造 PASS。
    """
    raw = getattr(ir, "branches", None)
    if not raw:
        return []
    branches = [_coerce(b) for b in raw]
    if len(branches) < 2:
        return []

    out: list[Finding] = []

    # 按分叉点分组：只有从**同一**故事点 (parent_point) 分叉的分支才互相可比。
    # None 一律视为同一个隐式根节点 —— 所有根分支共享同一个祖先。
    by_parent: dict[str | None, list[Branch]] = {}
    for b in branches:
        by_parent.setdefault(b.parent_point, []).append(b)

    for parent_point, group in by_parent.items():
        # 只有 ≥2 条分支的分叉点才构成「同一节点长出的不同可能世界」
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]

                # 1. 实体属性矛盾
                for eid, states in a.entity_states.items():
                    other = b.entity_states.get(eid)
                    if other is None:
                        continue
                    for attr, va in states.items():
                        if attr not in other:
                            continue
                        vb = other[attr]
                        if _contradictory(va, vb):
                            out.append(
                                _entity_contradiction(a, b, eid, attr, va, vb)
                            )

                # 2. 承诺前提被否定（双向）
                for cid in a.satisfied_commitments:
                    if cid in b.negated_commitments:
                        out.append(_commitment_negation(a, b, cid))
                for cid in b.satisfied_commitments:
                    if cid in a.negated_commitments:
                        out.append(_commitment_negation(b, a, cid))

    return out


__all__ = [
    "Branch",
    "attach_branches",
    "branch_consistency",
]
