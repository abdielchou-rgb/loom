"""显式状态转移语义校验器（`keel/validators/transitions.py`）单元测试。

RED-first：先写会失败的断言，再让实现通过；最后用变异测试证明
「禁忌态复现检查」是真正在工作的（翻成永不触发，反例必须变红）。

全部 IR 在本文件内构造（不动 `tests/fixtures.py`）：共享 fixture 是
集成方串行编辑的文件，往里塞东西会与别人的改动互踩。

跑法：
    .venv/Scripts/python.exe -m unittest discover -s tests -p "test_transitions.py" -v
    .venv/Scripts/python.exe tests/test_transitions.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keel.ir.enums import ArcShape, Focalization, Frequency, Medium, SceneOutcome, Severity  # noqa: E402
from keel.ir.models import (  # noqa: E402
    CommitmentLayer,
    NarrativeIR,
    SceneNode,
    StateDelta,
    TimePoint,
)
from keel.validators import transitions
from keel.validators.transitions import *  # noqa: F401,F403  （含 state_transition_integrity）


# ---------------------------------------------------------------------------
# IR 构造
# ---------------------------------------------------------------------------


def _build_ir(dead_reappears: bool) -> NarrativeIR:
    """构造一份 ≥7 场的 IR。

    * 角色 "C" 在 sc3 死亡（StateDelta: before="alive", after="dead",
      forbidden=["alive"]）。
    * 若 dead_reappears=True：C 在 sc7 重新作为 focalizer 出场（应触发禁忌态复现）。
    * 若 dead_reappears=False：C 死后不再以任何形式出场（干净基线，零发现）。
    """
    focalizers = ["C", "C", "C", "A", "B", "A", "C" if dead_reappears else "B"]
    scenes: list[SceneNode] = []
    for i in range(1, 8):
        foc = focalizers[i - 1]
        scenes.append(
            SceneNode(
                id=f"sc{i}",
                title=f"Scene {i}",
                focalizer=foc,
                narrator="narrator",
                fabula_time=TimePoint(day=i),
                sjuzhet_index=i - 1,
                value="trust",
                value_charge_start="+" if i % 2 == 1 else "-",
                value_charge_end="-" if i % 2 == 1 else "+",
                goal="g",
                conflict="c",
                turning_point=f"tp{i}",
                outcome=SceneOutcome.YES if i % 2 == 1 else SceneOutcome.NO,
                entities=[foc],
                focalization=Focalization.INTERNAL,
                frequency=Frequency.SINGULATIVE,
                state_deltas=[],
            )
        )
    # C 在 sc3 死亡
    scenes[2].state_deltas = [
        StateDelta(
            entity_id="C",
            attribute="status",
            before="alive",
            after="dead",
            forbidden=["alive"],
        )
    ]
    return NarrativeIR(
        title="Dead character counterexample",
        medium=Medium.NOVEL,
        commitment=CommitmentLayer(
            premise="p",
            controlling_idea="ci",
            logline="ll",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="sc7",
        ),
        scenes=scenes,
    )


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestStateTransitionIntegrity(unittest.TestCase):
    def test_counterexample_dead_reappears(self) -> None:
        """反例：C 在 sc3 死亡、在 sc7 重新作为 focalizer 出场 → 恰好 1 个 ERROR。"""
        ir = _build_ir(dead_reappears=True)
        findings = state_transition_integrity(ir)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.severity, Severity.ERROR)
        self.assertEqual(f.scene_id, "sc7")
        self.assertEqual(f.entity_id, "C")
        self.assertEqual(f.evidence["forbidden_set_at"], "sc3")
        self.assertEqual(f.evidence["entity_id"], "C")
        self.assertEqual(f.evidence["attribute"], "alive")

    def test_clean_baseline_no_reappearance(self) -> None:
        """干净基线：C 死后不再出场 → 0 个发现。"""
        ir = _build_ir(dead_reappears=False)
        findings = state_transition_integrity(ir)
        self.assertEqual(len(findings), 0)

    def test_backward_compat_state_delta(self) -> None:
        """向后兼容：不写 forbidden 的 StateDelta 仍能通过 extra='forbid' 校验。"""
        no_forbidden = StateDelta(
            entity_id="C", attribute="status", before="alive", after="dead"
        )
        self.assertIsNone(no_forbidden.forbidden)
        # 序列化往返后仍应无 forbidden（旧 IR 不丢字段）
        roundtrip = StateDelta.model_validate_json(no_forbidden.model_dump_json())
        self.assertIsNone(roundtrip.forbidden)
        # 写了 forbidden 也能正常校验与往返
        with_forbidden = StateDelta(
            entity_id="C",
            attribute="status",
            before="alive",
            after="dead",
            forbidden=["alive"],
        )
        self.assertEqual(with_forbidden.forbidden, ["alive"])

    def test_mutation_forbidden_disabled(self) -> None:
        """变异测试：把禁忌态复现检查翻成永不触发，反例必须不再产出 ERROR。

        这证明反例测试抓到的是「真实在工作的检查」，而不是偶然。
        若有人把 `_presence_violates` 翻成永远返回 False（即『让 forbidden
        检查永不触发』），上面的 test_counterexample 会立刻变红。
        """
        ir = _build_ir(dead_reappears=True)
        # 前置：反例当前确实产出 1 个 ERROR
        self.assertEqual(len(state_transition_integrity(ir)), 1)

        orig = transitions._presence_violates
        transitions._presence_violates = lambda scene, eid: False  # 翻成永不触发
        try:
            after = state_transition_integrity(ir)
        finally:
            transitions._presence_violates = orig
        self.assertEqual(len(after), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
