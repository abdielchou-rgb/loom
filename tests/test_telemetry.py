"""决策遥测（DecisionTelemetry）—— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**。

跑法：
    .venv/Scripts/python.exe tests/test_telemetry.py

零依赖（不用 pytest），与 `tests/test_csn.py` 同风格。

── 这个模块的目的，以及为什么它必须是纯内存的 ──────────────

目的写在源项目自己的注释里，值得原样保留：

> 「把『diff 接受率 / 拒绝率 / 来源→去向分布』变成可查数据，供周级门禁/
>   产品调参（避免靠感觉判断『作者是否信任 AI 提案』）」

也就是说：**「作者信不信任 AI 的提案」这句话，要么是一个可以查询的数字，
要么就是一句感觉。** 本模块的全部价值就是把它变成前者。

因此两条纪律：

  1. **不碰时钟。** 时间戳一律作为参数传入。取 `datetime.now()` 的结构
     写不出确定性测试，而一个测不准的指标会被当成噪声忽略掉 —— 那就退化
     回「靠感觉」了。第 1 组断言 `story_at` 原样保留调用方给的值。
  2. **不落盘。** 纯内存 + 纯函数式读取。落盘属于台账（`ProvenanceLedger`）
     的职责，混在一起会让「指标」和「记录」互相绑架。

── 三个口径的定义（第 2/3 组测的就是它们）────────────────

    裁决数 decisions  = 已裁决的条数 = accepted + rejected + conflicted
                        （pending 不是裁决，是「还没发生的事」，不进分母）
    accept_rate       = accepted / decisions      （decisions == 0 时为 0.0，不是崩溃）

`conflicted` 计入分母：作者先接受再拒绝，是对该提案的不信任信号，
把它排除在分母外会让采纳率虚高 —— 这正是本模块要防的「自欺指标」。

三个分布（来源卡 / 目标卡 / 字段）**数的是裁决**，因此各自的合计必须
恒等于 `decisions`。这不是巧合，是分区的定义 —— 第 3 组直接断言它。
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


# ---------------------------------------------------------------------------
# 构造工具 —— 复用真实的 Diff / ProposalSet，不造假对象
# ---------------------------------------------------------------------------


def _ps(*specs):
    """specs: (diff_id, source_card, target_card, field, verdict)"""
    from loom.ir.proposal import Diff, DiffStatus, ProposalSet

    ps = ProposalSet()
    for did, source, target, field, verdict in specs:
        ps.add(
            Diff(
                id=did,
                target_card=target,
                field=field,
                before="旧",
                after="新",
                rationale="因为小传改了，所以框架要跟着改",
                source_card=source,
            )
        )
        if verdict == "accept":
            ps.accept(did)
        elif verdict == "reject":
            ps.reject(did)
        elif verdict == "conflict":
            ps.accept(did)
            ps.reject(did)
        # verdict == "pending" -> 不动
    return ps


# ---------------------------------------------------------------------------
# 1. 记录：快照 + 时间戳由调用方给
# ---------------------------------------------------------------------------


def test_record(t: T) -> None:
    from loom.ir.proposal import DiffStatus
    from loom.provenance.telemetry import DecisionTelemetry

    t.group("1. 记录一次裁决")

    tel = DecisionTelemetry()
    ps = _ps(
        ("d1", "biography", "framework", "goal", "accept"),
        ("d2", "biography", "framework", "goal", "reject"),
    )
    tel.record(ps.get("d1"), story_at="第 3 章")
    tel.record(ps.get("d2"), story_at="第 3 章")

    t.eq(len(tel.records), 2, "两次记录")
    r = tel.records[0]
    t.eq(r.diff_id, "d1", "记录 diff id")
    t.eq(r.source_card, "biography", "记录来源卡")
    t.eq(r.target_card, "framework", "记录目标卡")
    t.eq(r.field, "goal", "记录字段")
    t.eq(r.status, DiffStatus.ACCEPTED, "记录裁决结果")
    t.eq(r.story_at, "第 3 章", "故事内时点原样保留调用方给的值（不取时钟）")
    t.eq(tel.records[1].status, DiffStatus.REJECTED, "第二条记录为 rejected")

    # 未给时间戳 → 留空，绝不用 now() 补一个假值
    tel.record(ps.get("d1"))
    t.eq(tel.records[-1].story_at, None, "未传时点 → 保持 None，不偷偷取 now()")

    t.eq(tel.decisions, 3, "decisions = 记录数（全部已裁决）")


# ---------------------------------------------------------------------------
# 2. 【核心】accept_rate 精确
# ---------------------------------------------------------------------------


def test_accept_rate(t: T) -> None:
    from loom.provenance.telemetry import DecisionTelemetry

    t.group("2. 【核心】accept_rate（精确数值）")

    tel = DecisionTelemetry()
    ps = _ps(
        ("d1", "biography", "framework", "goal", "accept"),
        ("d2", "biography", "framework", "goal", "accept"),
        ("d3", "biography", "framework", "goal", "accept"),
        ("d4", "sample", "biography", "wound", "reject"),
    )
    for d in ps.diffs:
        tel.record(d)

    t.eq(tel.decisions, 4, "裁决数 = 4")
    t.eq(tel.accept_rate, 0.75, "accept_rate = 3/4 = 0.75（精确相等，不用近似断言）")

    # conflicted 计入分母：先接受再拒绝 = 不信任，不能让它虚高采纳率
    tel2 = DecisionTelemetry()
    ps2 = _ps(
        ("d1", "biography", "framework", "goal", "accept"),
        ("d2", "biography", "framework", "goal", "conflict"),
    )
    for d in ps2.diffs:
        tel2.record(d)
    t.eq(tel2.decisions, 2, "conflicted 计入裁决数")
    t.eq(tel2.accept_rate, 0.5, "accept_rate = 1/2 = 0.5（conflicted 进了分母）")

    # 全拒绝
    tel3 = DecisionTelemetry()
    ps3 = _ps(("d1", "biography", "framework", "goal", "reject"))
    for d in ps3.diffs:
        tel3.record(d)
    t.eq(tel3.accept_rate, 0.0, "全拒绝 → 0.0")

    # 全接受
    tel4 = DecisionTelemetry()
    ps4 = _ps(("d1", "biography", "framework", "goal", "accept"))
    for d in ps4.diffs:
        tel4.record(d)
    t.eq(tel4.accept_rate, 1.0, "全接受 → 1.0")


# ---------------------------------------------------------------------------
# 3. 【核心】三个分布必须分区
# ---------------------------------------------------------------------------


def test_distributions(t: T) -> None:
    from loom.provenance.telemetry import DecisionTelemetry

    t.group("3. 【核心】三个分布各自分区")

    tel = DecisionTelemetry()
    ps = _ps(
        ("d1", "biography", "framework", "goal", "accept"),
        ("d2", "biography", "framework", "goal", "reject"),
        ("d3", "biography", "chapter", "value_turn", "accept"),
        ("d4", "sample", "biography", "wound", "accept"),
        ("d5", "sample", "biography", "lie", "conflict"),
        ("d6", "framework", "chapter", "summary", "pending"),
    )
    for d in ps.diffs:
        tel.record(d)

    t.eq(tel.decisions, 5, "六条记录里五条已裁决（pending 不进分母）")

    t.eq(
        tel.by_source_card(),
        {"biography": 3, "sample": 2},
        "按来源卡分布（framework 的 pending 提案不计入）",
    )
    t.eq(
        tel.by_target_card(),
        {"framework": 2, "chapter": 1, "biography": 2},
        "按目标卡分布",
    )
    t.eq(
        tel.by_field(),
        {"goal": 2, "value_turn": 1, "wound": 1, "lie": 1},
        "按字段分布",
    )

    for name, dist in (
        ("source_card", tel.by_source_card()),
        ("target_card", tel.by_target_card()),
        ("field", tel.by_field()),
    ):
        t.eq(sum(dist.values()), tel.decisions, f"{name} 分布合计 == 裁决数（分区）")

    # 输出确定性：键有序，逐次调用结果相同
    t.eq(
        list(tel.by_field().keys()),
        sorted(tel.by_field().keys()),
        "分布键有序（确定性输出，便于 diff 快照）",
    )
    t.eq(tel.by_field(), tel.by_field(), "同一状态两次调用结果相同")


# ---------------------------------------------------------------------------
# 4. 零裁决：不能除零
# ---------------------------------------------------------------------------


def test_zero_decision(t: T) -> None:
    from loom.provenance.telemetry import DecisionTelemetry

    t.group("4. 零裁决（不除零、不编造）")

    empty = DecisionTelemetry()
    t.eq(empty.decisions, 0, "空遥测 → 0 次裁决")
    t.eq(empty.accept_rate, 0.0, "空遥测 → accept_rate 0.0，不抛 ZeroDivisionError")
    t.eq(empty.by_source_card(), {}, "空遥测 → 空分布")
    t.eq(empty.by_target_card(), {}, "空遥测 → 空分布")
    t.eq(empty.by_field(), {}, "空遥测 → 空分布")

    # 只有 pending 提案：作者还没裁决，采纳率必须是 0.0 而不是 1.0/NaN
    tel = DecisionTelemetry()
    ps = _ps(
        ("d1", "biography", "framework", "goal", "pending"),
        ("d2", "biography", "framework", "goal", "pending"),
    )
    for d in ps.diffs:
        tel.record(d)
    t.eq(len(tel.records), 2, "两条记录都进了台账")
    t.eq(tel.decisions, 0, "但零条已裁决")
    t.eq(tel.accept_rate, 0.0, "全 pending → accept_rate 0.0（分母为零的显式口径）")
    t.eq(tel.by_field(), {}, "全 pending → 分布为空（不把未裁决混进分布）")


# ---------------------------------------------------------------------------
# 5. stats()：给产品调参用的机器可读汇总
# ---------------------------------------------------------------------------


def test_stats(t: T) -> None:
    from loom.provenance.telemetry import DecisionTelemetry

    t.group("5. stats() 汇总")

    tel = DecisionTelemetry()
    ps = _ps(
        ("d1", "biography", "framework", "goal", "accept"),
        ("d2", "biography", "framework", "goal", "reject"),
        ("d3", "sample", "biography", "wound", "conflict"),
    )
    for d in ps.diffs:
        tel.record(d, story_at="第 1 章")

    s = tel.stats()
    t.eq(s["decisions"], 3, "stats.decisions")
    t.eq(s["accepted"], 1, "stats.accepted")
    t.eq(s["rejected"], 1, "stats.rejected")
    t.eq(s["conflicted"], 1, "stats.conflicted")
    t.eq(s["accept_rate"], round(1 / 3, 4), "stats.accept_rate 四舍五入到 4 位")
    t.eq(s["by_source_card"], {"biography": 2, "sample": 1}, "stats.by_source_card")
    t.eq(s["by_target_card"], {"framework": 2, "biography": 1}, "stats.by_target_card")
    t.eq(s["by_field"], {"goal": 2, "wound": 1}, "stats.by_field")
    t.eq(
        s["accepted"] + s["rejected"] + s["conflicted"],
        s["decisions"],
        "stats 内部分区自洽",
    )


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  决策遥测 DecisionTelemetry —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_record(t)
        test_accept_rate(t)
        test_distributions(t)
        test_zero_decision(t)
        test_stats(t)
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
