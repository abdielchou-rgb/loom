"""`branch_consistency` 校验器测试（P6 · 2.0 互动叙事 —— 分支一致性）。

RED-first 纪律：
    先写会失败的断言（这里直接以最小可运行形态给出），再让实现通过。
    变异测试（把矛盾值翻成一致 → ERROR 消失）保证断言抓的是真缺陷，
    而不是「对着任何 IR 都报警」的伪命中。
"""

import unittest

from loom.ir.enums import ArcShape, Medium, Severity
from loom.ir.models import CommitmentLayer, NarrativeIR
from loom.validators.branches import (
    Branch,
    attach_branches,
    branch_consistency,
)


def _base_ir() -> NarrativeIR:
    return NarrativeIR(
        title="分支测试",
        medium=Medium.NOVEL,
        commitment=CommitmentLayer(
            premise="p",
            controlling_idea="c",
            logline="l",
            arc_shape=ArcShape.RAGS_TO_RICHES,
            ending_anchor="e",
        ),
    )


class BranchConsistencyTest(unittest.TestCase):
    # ---- 反例：两条同点分叉的分支对同一实体设定互斥状态 ----
    def test_contradiction_detected(self) -> None:
        ir = _base_ir()
        attach_branches(
            ir,
            [
                Branch(
                    id="A",
                    parent_point="node1",
                    entity_states={"X": {"status": "alive"}},
                ),
                Branch(
                    id="B",
                    parent_point="node1",
                    entity_states={"X": {"status": "dead"}},
                ),
            ],
        )
        fs = branch_consistency(ir)
        errors = [f for f in fs if f.severity is Severity.ERROR]
        self.assertGreaterEqual(len(errors), 1)
        f = errors[0]
        self.assertEqual(f.code, "branch_consistency")
        self.assertEqual(f.entity_id, "X")
        self.assertEqual(f.evidence["attribute"], "status")
        self.assertEqual(f.evidence["branch_a"], "A")
        self.assertEqual(f.evidence["branch_b"], "B")
        self.assertIn("矛盾", f.message)

    # ---- 干净基线：线性故事，无分支属性 → 必须返回 []（不是假 PASS）----
    def test_skip_when_no_branch_attr(self) -> None:
        ir = _base_ir()
        self.assertIsNone(getattr(ir, "branches", None))
        self.assertEqual(branch_consistency(ir), [])

    # ---- 干净：两条分支存在，但互不矛盾 → 零发现 ----
    def test_clean_two_branches_no_contradiction(self) -> None:
        ir = _base_ir()
        attach_branches(
            ir,
            [
                Branch(
                    id="A",
                    parent_point="node1",
                    entity_states={"X": {"status": "alive"}},
                ),
                Branch(
                    id="B",
                    parent_point="node1",
                    entity_states={"Y": {"status": "dead"}},
                ),
            ],
        )
        self.assertEqual(branch_consistency(ir), [])

    # ---- 单条分支不足以构成比较 → 零发现 ----
    def test_single_branch_no_finding(self) -> None:
        ir = _base_ir()
        attach_branches(ir, [Branch(id="A", entity_states={"X": {"status": "alive"}})])
        self.assertEqual(branch_consistency(ir), [])

    # ---- 变异：把矛盾值翻成一致 → ERROR 消失 ----
    def test_mutation_flip_resolves(self) -> None:
        ir = _base_ir()
        attach_branches(
            ir,
            [
                Branch(
                    id="A",
                    parent_point="node1",
                    entity_states={"X": {"status": "alive"}},
                ),
                Branch(
                    id="B",
                    parent_point="node1",
                    entity_states={"X": {"status": "dead"}},
                ),
            ],
        )
        before = [f for f in branch_consistency(ir) if f.severity is Severity.ERROR]
        self.assertGreaterEqual(len(before), 1)
        # 翻 B 的取值，使其与 A 一致
        attach_branches(
            ir,
            [
                Branch(
                    id="A",
                    parent_point="node1",
                    entity_states={"X": {"status": "alive"}},
                ),
                Branch(
                    id="B",
                    parent_point="node1",
                    entity_states={"X": {"status": "alive"}},
                ),
            ],
        )
        after = [f for f in branch_consistency(ir) if f.severity is Severity.ERROR]
        self.assertEqual(after, [])

    # ---- 承诺前提被否定：分支 A 满足 C1、分支 B 否定 C1 的前提 ----
    def test_commitment_premise_negation(self) -> None:
        ir = _base_ir()
        attach_branches(
            ir,
            [
                Branch(id="A", parent_point="node1", satisfied_commitments=["C1"]),
                Branch(id="B", parent_point="node1", negated_commitments=["C1"]),
            ],
        )
        fs = branch_consistency(ir)
        errors = [
            f
            for f in fs
            if f.severity is Severity.ERROR and f.evidence.get("commitment_id") == "C1"
        ]
        self.assertEqual(len(errors), 1)
        self.assertIn("C1", errors[0].message)

    # ---- 承诺前提否定变异：撤销否定 → ERROR 消失 ----
    def test_commitment_negation_mutation(self) -> None:
        ir = _base_ir()
        attach_branches(
            ir,
            [
                Branch(id="A", parent_point="node1", satisfied_commitments=["C1"]),
                Branch(id="B", parent_point="node1", negated_commitments=["C1"]),
            ],
        )
        self.assertGreaterEqual(
            len(
                [
                    f
                    for f in branch_consistency(ir)
                    if f.severity is Severity.ERROR
                    and f.evidence.get("commitment_id") == "C1"
                ]
            ),
            1,
        )
        # 把 B 的 negated 清空 → 不再矛盾
        attach_branches(
            ir,
            [
                Branch(id="A", parent_point="node1", satisfied_commitments=["C1"]),
                Branch(id="B", parent_point="node1"),
            ],
        )
        self.assertEqual(
            [
                f
                for f in branch_consistency(ir)
                if f.severity is Severity.ERROR
                and f.evidence.get("commitment_id") == "C1"
            ],
            [],
        )

    # ---- 不同分叉点的分支不互相比较（避免误报）----
    def test_different_parent_points_not_compared(self) -> None:
        ir = _base_ir()
        attach_branches(
            ir,
            [
                Branch(
                    id="A",
                    parent_point="node1",
                    entity_states={"X": {"status": "alive"}},
                ),
                Branch(
                    id="B",
                    parent_point="node2",
                    entity_states={"X": {"status": "dead"}},
                ),
            ],
        )
        self.assertEqual(branch_consistency(ir), [])


if __name__ == "__main__":
    unittest.main()
