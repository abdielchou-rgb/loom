"""提案协议（Diff / ProposalSet）—— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**。

跑法：
    .venv/Scripts/python.exe tests/test_proposal.py

零依赖（不用 pytest），与 `tests/test_csn.py` 同风格。

── 这个模块要防的是什么 ────────────────────────────────

Loom 的 `CriticLoop` **自动应用**修订（目前只限文风类）。本模块把「结构类」
从「留给人决策」升级为「生成提案，人一键采纳」——铁律是
**永不静默改写**（Æsirian `core/diff_engine.py`；原型是 Pensive 的
"what you pin, the AI must keep"）。

所以测试的重心不是「能存一条 Diff」，而是**裁决的状态机**：

  1. 裁决必须**可逆地不生效** —— reject 之后，`after` 绝不能落到目标卡上。
     第 2 组断言 `Diff.before` / `after` 只是**提案内容**，`status` 才是
     唯一的「是否生效」开关；消费方读的是 status，不是 after。
  2. 重复裁决不能损坏状态。同向重复 = 幂等（作者重复点同一个按钮不该
     产生冲突）；反向重复 = `conflicted`（作者自相矛盾是要被记录下来的
     事实，不是要被抛掉的异常 —— 第 4 组的遥测要数它）。
  3. 计数必须自洽：四种状态计数之和恒等于提案总数。计数不自洽的仪表盘
     比没有仪表盘更危险。

── 期望值的来源 ────────────────────────────────────────

四种状态 `pending / accepted / rejected / conflicted` 直接取自
`aesirian_吸收评估.md` ⑦ 的 `Diff` 数据结构定义，不是本模块自创的。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 极简断言框架（与 tests/test_csn.py 同款，不引入 pytest）
# ---------------------------------------------------------------------------


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


def raises(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------


def _diff(
    did: str = "d1",
    *,
    target: str = "framework",
    field: str = "goal",
    before: object = "夺回钥匙",
    after: object = "放弃钥匙",
    rationale: str = "因为小传里母亲已死，所以夺回钥匙的动机不成立",
    source: str = "biography",
    status=None,
):
    from loom.ir.proposal import Diff, DiffStatus

    return Diff(
        id=did,
        target_card=target,
        field=field,
        before=before,
        after=after,
        rationale=rationale,
        source_card=source,
        status=status or DiffStatus.PENDING,
    )


def _set(*diffs):
    from loom.ir.proposal import ProposalSet

    ps = ProposalSet()
    for d in diffs:
        ps.add(d)
    return ps


# ---------------------------------------------------------------------------
# 1. Diff 数据结构
# ---------------------------------------------------------------------------


def test_diff_model(t: T) -> None:
    from loom.ir.proposal import Diff, DiffStatus

    t.group("1. Diff / DiffStatus")

    t.eq(DiffStatus.PENDING.value, "pending", "状态·pending")
    t.eq(DiffStatus.ACCEPTED.value, "accepted", "状态·accepted")
    t.eq(DiffStatus.REJECTED.value, "rejected", "状态·rejected")
    t.eq(DiffStatus.CONFLICTED.value, "conflicted", "状态·conflicted")

    d = _diff()
    t.eq(d.status, DiffStatus.PENDING, "新建提案默认待裁决（不默认生效！）")
    t.eq(d.before, "夺回钥匙", "before 保留原值")
    t.eq(d.after, "放弃钥匙", "after 是提案值，不是已生效值")
    t.eq(d.source_card, "biography", "来源卡")
    t.eq(d.target_card, "framework", "目标卡")
    t.eq(d.field, "goal", "字段名")

    # 十一个字段，不多不少 —— 防止悄悄塞进「已应用」之类的影子状态。
    # `proposed_at` / `decided_at` / `decided_by` 是 2026-09-17 加的举证字段：
    # 一条只写着 rejected 的记录说不出「谁在何时驳回了它」，那不是证据。
    t.eq(
        sorted(d.model_dump().keys()),
        sorted(
            [
                "id",
                "target_card",
                "field",
                "before",
                "after",
                "rationale",
                "source_card",
                "status",
                "proposed_at",
                "decided_at",
                "decided_by",
            ]
        ),
        "Diff 字段集合与设计一致",
    )
    t.eq(d.proposed_at, None, "新建提案未填提出时刻（等待调用方注入）")
    t.eq(d.decided_at, None, "新建提案未填裁决时刻")
    t.eq(d.decided_by, None, "新建提案**不默认**裁决者是 human（谁裁的誰填）")

    t.ok(
        raises(
            lambda: Diff(
                id="x", target_card="t", field="f", before=1, after=2,
                rationale="r", source_card="s", typo=1,
            )
        ),
        "未知字段被拒绝（extra=forbid）",
    )
    t.ok(
        raises(
            lambda: Diff(
                id="x", target_card="t", field="f", before=1, after=2,
                rationale="r", source_card="s", status="不是状态",
            )
        ),
        "非法状态被拒绝",
    )


# ---------------------------------------------------------------------------
# 2. 裁决：pending -> accepted / rejected
# ---------------------------------------------------------------------------


def test_resolve(t: T) -> None:
    from loom.ir.proposal import DiffStatus

    t.group("2. 裁决状态迁移")

    ps = _set(_diff("d1"), _diff("d2"), _diff("d3"))
    t.eq(len(ps.pending()), 3, "初始三条待裁决")
    t.eq(ps.get("d1").status, DiffStatus.PENDING, "d1 初始 pending")

    out = ps.accept("d1")
    t.eq(out.status, DiffStatus.ACCEPTED, "accept 返回被裁决的提案（可直接喂遥测）")
    t.eq(ps.get("d1").status, DiffStatus.ACCEPTED, "d1 → accepted")
    t.eq(len(ps.pending()), 2, "pending 列表收缩")

    ps.reject("d2")
    t.eq(ps.get("d2").status, DiffStatus.REJECTED, "d2 → rejected")
    t.eq(len(ps.pending()), 1, "pending 再收缩")

    # 未裁决的提案绝不能算已生效：消费方读 status，不读 after
    t.eq(ps.get("d3").status, DiffStatus.PENDING, "未裁决的仍是 pending")
    t.eq(ps.get("d3").after, "放弃钥匙", "after 一直在，但 status 未变 → 不得应用")

    # 未知 id = 编程错误，不是作者行为
    t.ok(raises(lambda: ps.accept("不存在")), "裁决未知 id → 抛错")
    t.ok(raises(lambda: ps.reject("不存在")), "拒绝未知 id → 抛错")

    t.group("2b. 重复 add 同一 id")
    t.ok(raises(lambda: _set(_diff("d1"), _diff("d1"))), "重复 id → 抛错（否则遥测分组被污染）")


# ---------------------------------------------------------------------------
# 3. 双重裁决
# ---------------------------------------------------------------------------


def test_double_resolve(t: T) -> None:
    from loom.ir.proposal import DiffStatus

    t.group("3. 双重裁决（同向幂等 / 反向 conflicted）")

    ps = _set(_diff("d1"))
    ps.accept("d1")
    again = ps.accept("d1")
    t.eq(again.status, DiffStatus.ACCEPTED, "同向重复裁决 → 幂等，状态不变")
    t.eq(ps.counts()["accepted"], 1, "同向重复裁决不产生第二条 accepted")

    ps2 = _set(_diff("d1"))
    ps2.reject("d1")
    t.eq(ps2.reject("d1").status, DiffStatus.REJECTED, "同向重复 reject → 幂等")

    # 反向裁决 = 作者自相矛盾 → 记为 conflicted（这是要被数出来的事实）
    ps3 = _set(_diff("d1"))
    ps3.accept("d1")
    flip = ps3.reject("d1")
    t.eq(flip.status, DiffStatus.CONFLICTED, "接受后再拒绝 → conflicted")
    t.eq(ps3.counts()["accepted"], 0, "conflicted 后不再计为 accepted")
    t.eq(ps3.counts()["conflicted"], 1, "conflicted 计入 conflicted")

    ps4 = _set(_diff("d1"))
    ps4.reject("d1")
    t.eq(ps4.accept("d1").status, DiffStatus.CONFLICTED, "拒绝后再接受 → conflicted")

    # conflicted 是终态：再裁决不再翻转（否则遥测会数到漂移的状态）
    t.eq(ps3.accept("d1").status, DiffStatus.CONFLICTED, "conflicted 是终态")
    t.eq(ps3.counts()["conflicted"], 1, "终态重复裁决不新增计数")


# ---------------------------------------------------------------------------
# 4. 计数自洽
# ---------------------------------------------------------------------------


def test_counts(t: T) -> None:
    t.group("4. 计数一致性")

    ps = _set()
    t.eq(
        ps.counts(),
        {"pending": 0, "accepted": 0, "rejected": 0, "conflicted": 0},
        "空集合 → 全零（键必须齐备，否则前端仪表盘会 KeyError）",
    )
    t.eq(ps.pending(), [], "空集合 → 空 pending 列表")

    ps = _set(_diff("d1"), _diff("d2"), _diff("d3"), _diff("d4"), _diff("d5"))
    ps.accept("d1")
    ps.accept("d2")
    ps.reject("d3")
    ps.accept("d4")
    ps.reject("d4")  # -> conflicted
    # d5 留作 pending

    counts = ps.counts()
    t.eq(
        counts,
        {"pending": 1, "accepted": 2, "rejected": 1, "conflicted": 1},
        "五种裁决混合后的精确计数",
    )
    t.eq(
        sum(counts.values()),
        len(ps.diffs),
        "四态计数之和 == 提案总数（分区，不重不漏）",
    )
    t.eq(len(ps.pending()), counts["pending"], "pending() 长度与计数一致")

    # 每个 diff 恰好落在一个桶里
    buckets = [ps.get(d.id).status.value for d in ps.diffs]
    t.eq(
        sorted(buckets),
        ["accepted", "accepted", "conflicted", "pending", "rejected"],
        "每条提案的最终状态",
    )


# ---------------------------------------------------------------------------
# 5. 举证字段：谁在何时裁的
# ---------------------------------------------------------------------------


def test_evidence_fields(t: T) -> None:
    """`proposed_at` / `decided_at` / `decided_by` 的落章规则。

    为什么这组断言值得单列：合规申诉要的是**主张证据**「这些判断是人类做的」。
    一条 `status=rejected` 只说明有人按了拒绝 —— 说不出谁、什么时候。
    没有这三个字段，「人做过判断」就只是一句主张。

    最要防的两种坏实现：
      * **同向重复裁决把首次时刻冲掉** —— 作者重复点一次按钮，
        「第一次判断的时刻」就没了，而那正是举证要看的时刻。
      * **没传时刻就拒绝裁决** —— 让一个元数据字段绑架控制流。
        没有时刻的裁决仍是一次合法裁决，只是举证力弱一些。
    """
    from loom.ir.proposal import DiffStatus

    t.group("5. 举证字段（时刻 / 主体）")

    ps = _set(_diff("d1"), _diff("d2"), _diff("d3"), _diff("d4"))

    # 5a. 正常裁决 → 落章
    ps.get("d1").proposed_at = "2026-09-17T14:01:03+00:00"
    ps.accept("d1", decided_at="2026-09-17T14:02:11+00:00", decided_by="human")
    t.eq(ps.get("d1").status, DiffStatus.ACCEPTED, "5a 状态 → accepted")
    t.eq(
        ps.get("d1").decided_at,
        "2026-09-17T14:02:11+00:00",
        "5a 裁决时刻落章",
    )
    t.eq(ps.get("d1").decided_by, "human", "5a 裁决主体落章")
    t.eq(
        ps.get("d1").proposed_at,
        "2026-09-17T14:01:03+00:00",
        "5a 提出时刻不受裁决影响（两个时刻各管一段）",
    )

    # 5b. 同向重复裁决 → **不**覆盖时刻（幂等不是新的一次判断）
    ps.accept("d1", decided_at="2026-09-18T09:00:00+00:00", decided_by="human")
    t.eq(
        ps.get("d1").decided_at,
        "2026-09-17T14:02:11+00:00",
        "5b 同向重复裁决不冲掉首次判断的时刻",
    )

    # 5c. 未传时刻 → 状态照常迁移，时刻留空（元数据不许绑架控制流）
    ps.reject("d2")
    t.eq(ps.get("d2").status, DiffStatus.REJECTED, "5c 没时刻也能裁决")
    t.eq(ps.get("d2").decided_at, None, "5c 未传 → 留空，不偷偷取 now()")
    t.eq(ps.get("d2").decided_by, None, "5c 未传 → 主体留空（不默认是 human）")

    # 5d. 反向裁决 → conflicted，且**覆盖**时刻：
    #     status 与 decided_at 必须描述同一次裁决，否则这条记录自相矛盾
    #     （它声称「在 T 时刻裁决为 rejected」，而 T 时刻其实是 accepted）
    ps.accept("d3", decided_at="2026-09-17T15:00:00+00:00", decided_by="human")
    ps.reject("d3", decided_at="2026-09-17T16:30:00+00:00", decided_by="human")
    t.eq(ps.get("d3").status, DiffStatus.CONFLICTED, "5d 反向裁决 → conflicted")
    t.eq(
        ps.get("d3").decided_at,
        "2026-09-17T16:30:00+00:00",
        "5d conflicted 与时刻对应同一次裁决（覆盖，不是留旧值）",
    )

    # 5e. 机器代裁：主体如实写机器。**默认 human 会让采纳率被自己灌水**
    ps.accept("d4", decided_at="2026-09-17T17:00:00+00:00", decided_by="machine:mock")
    t.eq(ps.get("d4").decided_by, "machine:mock", "5e 机器代裁如实署名")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  提案协议 Diff / ProposalSet —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_diff_model(t)
        test_resolve(t)
        test_double_resolve(t)
        test_counts(t)
        test_evidence_fields(t)
    except ImportError as exc:
        print(f"\n  ✗ 模块尚不存在（RED 阶段预期如此）：{exc}")
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
