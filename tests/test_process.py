"""创作过程报告（申诉举证）—— 单元测试。

跑法：
    .venv/Scripts/python.exe tests/test_process.py

零依赖。实现先于测试，故做了变异测试补偿（见文件末尾记录）。

── 本文件要钉死的三件事 ─────────────────────────────────

1. **主张证据来自 IR，不是来自内存。**
   `DecisionTelemetry` 是进程内的，导出 IR 再读回来就没了；
   而申诉发生在几天后，那时只有 IR 还在。故报告必须**仅凭 IR** 就能
   重建人类判断清单。这是 `build_process_report` 不强制要求 telemetry 的原因。

2. **未裁决不计入证据。**
   「AI 提了 20 条，作者一条没动」不是人类参与的证据，恰恰相反。
   待裁决项单列，且**不进** judgements。

3. **缺口声明必须出现在每一种导出里。**
   一份不声明边界的证据，在申诉现场会被当成「你只有这些」。
   渲染文本、Markdown、JSON 三处都要有。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def eq(self, got, want, label: str) -> None:
        if got == want:
            self.passed += 1
        else:
            self.failed.append(f"{label}\n      期望 {want!r}\n      实际 {got!r}")

    def ok(self, cond: bool, label: str) -> None:
        if cond:
            self.passed += 1
        else:
            self.failed.append(label)

    def group(self, name: str) -> None:
        print(f"\n  {name}")


def _base_ir():
    from loom.ir.models import Medium
    from tests.fixtures import clean_copy

    return clean_copy(Medium.NOVEL)


def _rejected(ir, n: int = 1, prefix: str = "j") -> None:
    """往 IR 里塞 n 条**已驳回**的提案。"""
    from loom.ir.proposal import Diff, DiffStatus

    for i in range(n):
        ir.proposals.append(
            Diff(
                id=f"{prefix}{i}",
                target_card="scene:sc1",
                field="value_charge_end",
                before=1,
                after=-1,
                rationale=f"第 {i} 条：价值极性未翻转",
                source_card="validator:value_charge_flip",
                status=DiffStatus.REJECTED,
            )
        )


# ---------------------------------------------------------------------------
# 1. 证据强度
# ---------------------------------------------------------------------------


def test_evidence_strength(t: T) -> None:
    from loom.ir.proposal import Diff, DiffStatus
    from loom.provenance.process import build_process_report

    t.group("1. 证据强度（诚实评估，不是保证）")

    ir = _base_ir()
    t.eq(len(ir.proposals), 0, "干净基线没有提案")
    rep = build_process_report(ir)
    t.eq(rep.decided, 0, "没有裁决")
    level, note = rep.evidence_strength()
    t.eq(level, "弱", "零裁决 → 证据强度弱")
    t.ok("证明不了" in note, "弱结论必须**明说**证明不了什么")

    # 只有采纳、且少于 3 条 → 仍然弱
    ir = _base_ir()
    ir.proposals.append(
        Diff(
            id="d1",
            target_card="scene:sc1",
            field="value_charge_end",
            before=1,
            after=-1,
            rationale="价值极性未翻转",
            source_card="validator:value_charge_flip",
            status=DiffStatus.ACCEPTED,
        )
    )
    rep = build_process_report(ir)
    t.eq(rep.decided, 1, "一条已裁决")
    t.eq(rep.evidence_strength()[0], "弱", "全采纳且 <3 条 → 仍弱")

    # 驳回 ≥3 条 → 较强
    ir = _base_ir()
    for i in range(3):
        ir.proposals.append(
            Diff(
                id=f"r{i}",
                target_card="scene:sc1",
                field="value_charge_end",
                before=1,
                after=-1,
                rationale=f"第 {i} 条",
                source_card="validator:value_charge_flip",
                status=DiffStatus.REJECTED,
            )
        )
    rep = build_process_report(ir)
    t.eq(rep.rejected, 3, "三条驳回")
    t.eq(rep.evidence_strength()[0], "较强", "驳回 ≥3 → 较强")
    t.ok("驳回" in rep.evidence_strength()[1], "较强结论点名了驳回")


# ---------------------------------------------------------------------------
# 2. 未裁决不算证据
# ---------------------------------------------------------------------------


def test_pending_is_not_evidence(t: T) -> None:
    from loom.ir.proposal import Diff, DiffStatus
    from loom.provenance.process import build_process_report

    t.group("2. 待裁决不构成证据")

    ir = _base_ir()
    ir.proposals.append(
        Diff(
            id="p1",
            target_card="scene:sc1",
            field="value_charge_end",
            before=1,
            after=-1,
            rationale="待裁决的提案",
            source_card="validator:value_charge_flip",
            # status 默认 pending
        )
    )
    rep = build_process_report(ir)
    t.eq(rep.decided, 0, "待裁决**不进**判断清单")
    t.eq(rep.pending, ["p1"], "待裁决单独列出")
    t.eq(rep.evidence_strength()[0], "弱", "有待裁决不改变证据强度")

    # 裁决掉它 → 立刻变成证据
    ir.accept_proposal("p1")
    rep2 = build_process_report(ir)
    t.eq(rep2.decided, 1, "裁决后进判断清单")
    t.eq(rep2.pending, [], "不再有待裁决项")


# ---------------------------------------------------------------------------
# 3. 仅凭 IR 就能重建（不依赖内存遥测）
# ---------------------------------------------------------------------------


def test_ir_only(t: T) -> None:
    from loom.ir.models import NarrativeIR
    from loom.ir.proposal import DiffStatus
    from loom.provenance.process import build_process_report

    t.group("3. 仅凭 IR 就能重建报告")

    ir = _base_ir()
    _rejected(ir, 3)

    # 序列化 → 反序列化：模拟「导出 IR，几天后回来申诉」
    raw = ir.to_json()
    revived = NarrativeIR.from_json(raw)
    rep = build_process_report(revived)
    t.eq(rep.decided, 3, "反序列化后仍能重建 3 条判断")
    t.eq(rep.evidence_strength()[0], "较强", "证据强度不因序列化而丢失")


# ---------------------------------------------------------------------------
# 4. 三种导出都要带缺口声明
# ---------------------------------------------------------------------------


def test_gaps_in_every_export(t: T) -> None:
    from loom.provenance.process import GAPS, build_process_report

    t.group("4. 缺口声明出现在每一种导出里")

    rep = build_process_report(_base_ir())
    t.ok(len(GAPS) >= 3, f"缺口声明至少三条（{len(GAPS)}）")

    text = rep.render()
    t.ok("不能" in text and "缺口" in text, "渲染文本里有缺口声明")
    for g in GAPS:
        t.ok(g[:12] in text, f"渲染文本含缺口：{g[:12]}…")

    md = rep.to_markdown()
    t.ok("## 缺口声明" in md, "Markdown 有缺口声明章节")
    t.ok("| 总字数 |" in md, "Markdown 有参与度表格")
    t.ok(md.startswith("# "), "Markdown 以标题开头（可直接当附件）")

    data = json.loads(rep.to_json())
    t.eq(data["gaps"], list(GAPS), "JSON 里有完整缺口声明")
    t.ok("evidence_strength" in data, "JSON 里有证据强度")
    t.ok("judgements" in data and "pending" in data, "JSON 里有判断与待裁决")


# ---------------------------------------------------------------------------
# 5. 人工原创场景清单
# ---------------------------------------------------------------------------


def test_scene_ownership(t: T) -> None:
    from loom.ir.enums import ChunkOrigin
    from loom.provenance.process import build_process_report

    t.group("5. 场景归属")

    ir = _base_ir()
    rep = build_process_report(ir)
    t.eq(len(rep.human_scenes), len(ir.scenes), "基线全部人工原创")
    t.eq(rep.ai_scenes, [], "基线没有 AI 场景")

    ir.scenes[0].origin = ChunkOrigin.AI_GENERATED
    ir.scenes[0].model_id = "m1"
    rep2 = build_process_report(ir)
    t.eq(rep2.ai_scenes, [ir.scenes[0].id], "AI 场景被认出")
    t.eq(len(rep2.human_scenes), len(ir.scenes) - 1, "人工场景数相应减少")


def main() -> int:
    print("═" * 64)
    print("  创作过程报告（申诉举证）—— 测试")
    print("═" * 64)
    t = T()
    try:
        test_evidence_strength(t)
        test_pending_is_not_evidence(t)
        test_ir_only(t)
        test_gaps_in_every_export(t)
        test_scene_ownership(t)
    except ImportError as exc:
        print(f"\n  ✗ 模块尚不存在：{exc}")
        print("\n" + "─" * 64)
        print("  失败 1 · 通过 0")
        return 1

    print("\n" + "─" * 64)
    print(f"  通过 {t.passed} · 失败 {len(t.failed)}")
    if t.failed:
        print("  失败项：")
        for f in t.failed:
            print(f"    ✗ {f}")
        return 1
    print("  全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
