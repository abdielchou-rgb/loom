"""自动驾驶 · 续跑不得覆盖人类裁决 —— 测试先行。

跑法：
    .venv/Scripts/python.exe tests/test_auto_resume.py

── 这个测试要防的事 ────────────────────────────────────────────
自动驾驶暂停等人，人裁决完（`keel decide`），再跑一次同一条命令续上。
检查点里存的是**机器暂停那一刻**的 IR —— 人在那之后做的裁决不在里面。
若续跑直接采用检查点，作者刚驳回的提案会复活成 pending，
那次驳回连痕迹都不留。

这不是「数据丢失」这种抽象风险，是**本功能存在的理由被自己推翻**：
整套留痕是为了证明「人做过判断」，而续跑把判断擦掉，等于系统亲口
演示了一次「人的判断不算数」。

── 判据 ────────────────────────────────────────────────────────
  1. 指定 `--resume-from` 时，**无条件**采用人那份 IR（它是人的最新真值）
  2. 人类裁决**读回台账**（`decisions` 里出现 `human_verdict` + 时刻）
  3. 没指定但有 `paused.json` → **响亮警告**，不是静默选择
  4. 台账从 IR 派生：IR 与 decisions.json 不可能各说一套
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
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


# ---------------------------------------------------------------------------


def _run(tmp: Path, **kw):
    """跑一次自动驾驶（离线桩件），返回 (result, writer)。"""
    from keel.llm.mock import MockGenerator
    from keel.pipeline.auto import AutoConfig, AutoWriter

    writer = AutoWriter(
        MockGenerator(),
        cfg=AutoConfig(target_scenes=kw.get("target_scenes", 2), words_per_scene=60),
        clock=lambda: "2026-09-17T01:00:00+08:00",
    )
    res = writer.run(
        "一个替人收尸的刀客，最后一次收尸收到自己师父",
        checkpoint_dir=kw.get("checkpoint_dir"),
        resume_ir=kw.get("resume_ir"),
    )
    return res, writer


def test_roundtrip(t: T) -> None:
    """跑一次 → 人裁决 → 从人那份续跑 → 裁决还在。"""
    from keel.ir.models import NarrativeIR

    t.group("1. 机器提案（离线跑一次）")
    tmp = Path(tempfile.mkdtemp(prefix="keel_resume_"))
    try:
        res, _ = _run(tmp, checkpoint_dir=tmp / ".auto")
        t.ok(len(res.ir.proposals) >= 1, f"至少产生 1 条结构提案（实际 {len(res.ir.proposals)}）")
        if not res.ir.proposals:
            return
        pid = res.ir.proposals[0].id
        t.eq(res.ir.proposals[0].status.value, "pending", "机器提案初始为待裁决")
        t.ok(res.ir.proposals[0].proposed_at is not None, "机器提案带提出时刻")
        t.eq(
            res.decisions[0]["kind"],
            "machine_proposal",
            "台账首条是机器提案",
        )
        t.eq(res.decisions[0]["proposed_by"], res.ir.proposals[0].source_card,
             "台账的提出方 == 提案的 source_card（派生，不是另存一份）")

        t.group("2. 人类裁决（在 Keel 进程之外发生）")
        human_path = tmp / "human_ir.json"
        human_path.write_text(res.ir.to_json(), encoding="utf-8")
        hir = NarrativeIR.from_json(human_path.read_text(encoding="utf-8"))
        hir.reject_proposal(
            pid, decided_at="2026-09-17T01:10:00+08:00", decided_by="human:作者本人"
        )
        human_path.write_text(hir.to_json(), encoding="utf-8")

        t.group("3. 从人工修订版续跑")
        res2, _ = _run(tmp, checkpoint_dir=tmp / ".auto", resume_ir=human_path)
        again = next((d for d in res2.ir.proposals if d.id == pid), None)
        t.ok(again is not None, "那条提案还在")
        if again is None:
            return
        # 核心断言：人的裁决**没有被检查点覆盖**
        t.eq(again.status.value, "rejected", "★ 人类裁决在续跑后仍然成立（没被复活成 pending）")
        t.eq(again.decided_at, "2026-09-17T01:10:00+08:00", "裁决时刻保留")
        t.eq(again.decided_by, "human:作者本人", "裁决主体保留")

        t.group("4. 人类裁决读回台账")
        kinds = [d["kind"] for d in res2.decisions]
        t.ok("human_verdict" in kinds, f"台账出现 human_verdict（实际 {kinds}）")
        v = next((d for d in res2.decisions if d["kind"] == "human_verdict"), None)
        if v:
            t.eq(v["diff_id"], pid, "裁决记录指向同一条提案")
            t.eq(v["decided_at"], "2026-09-17T01:10:00+08:00", "台账带裁决时刻")
            t.eq(v["decided_by"], "human:作者本人", "台账带裁决主体")
            t.eq(v["proposed_at"], res.ir.proposals[0].proposed_at,
                 "台账保留**提出**时刻 → 完整的「机器提议 → 人类判断」链")
        joined = "\n".join(res2.log)
        t.ok("从人工修订版续跑" in joined, "日志里写明这次是从人工修订版续跑")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_warn_without_resume(t: T) -> None:
    """有 paused.json 却没指定 --resume-from → 必须警告，不能静默。"""
    t.group("5. 未指定 --resume-from 时的警告")
    tmp = Path(tempfile.mkdtemp(prefix="keel_resume_warn_"))
    try:
        ck = tmp / ".auto"
        ck.mkdir(parents=True, exist_ok=True)
        # 造一个「人在那里裁过」的现场：目录里躺着暂停副本
        (ck / "paused.json").write_text("{}", encoding="utf-8")
        res, _ = _run(tmp, checkpoint_dir=ck)
        joined = "\n".join(res.log)
        t.ok("paused.json" in joined, "日志提到了那份人工修订副本")
        t.ok("不会被继承" in joined, "★ 明确告知：本次裁决不会被继承（不许静默）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_entry_shape(t: T) -> None:
    """台账条目 = 提案的视图，两份不可能各说一套。"""
    from keel.ir.proposal import Diff, DiffStatus
    from keel.pipeline.auto import _decision_entries, _decided_count

    t.group("6. 台账派生自 IR")
    d1 = Diff(id="a", target_card="scene:sc2", field="append", before=None,
              after={}, rationale="r", source_card="auto:mock",
              proposed_at="T0")
    d2 = Diff(id="b", target_card="scene:sc3", field="append", before=None,
              after={}, rationale="r", source_card="auto:mock",
              proposed_at="T1", status=DiffStatus.REJECTED,
              decided_at="T2", decided_by="human")

    class _IR:
        proposals = [d1, d2]

    entries = _decision_entries(_IR())  # type: ignore[arg-type]
    t.eq(len(entries), 2, "两条提案 → 两条台账")
    t.eq(entries[0]["kind"], "machine_proposal", "未裁决 → 机器提案")
    t.eq(entries[0]["scene_id"], "sc2", "scene_id 从 target_card 解析")
    t.eq(entries[1]["kind"], "human_verdict", "已裁决 → 人类裁决")
    t.eq(entries[1]["decided_by"], "human", "裁决主体透传")
    t.eq(_decided_count(_IR()), 1, "已裁决数 = 1（只数非 pending）")  # type: ignore[arg-type]

    # 派生 ⇒ JSON 化后仍保持一致（台账不是另一份状态）
    t.eq(
        json.loads(json.dumps(entries))[1]["diff_id"],
        "b",
        "台账可序列化，且与提案同 id",
    )


def main() -> int:
    print("═" * 64)
    print("  自动驾驶续跑 × 人类裁决 —— 测试")
    print("═" * 64)
    t = T()
    try:
        test_roundtrip(t)
        test_warn_without_resume(t)
        test_entry_shape(t)
    except ImportError as exc:
        print(f"\n  ✗ 模块尚不存在（RED 阶段预期如此）：{exc}")
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
