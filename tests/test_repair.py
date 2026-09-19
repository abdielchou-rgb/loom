"""修复预算与冲突消解（keel.pipeline.repair）—— 测试先行，含变异验证。

跑法：
    .venv/Scripts/python.exe tests/test_repair.py

零依赖（不用 pytest），与 `tests/test_budget.py` 同风格：一个极简 `T`
（ok/eq/group）+ `main() -> int`，失败返回非 0（`scripts/verify.py` 会
glob `tests/test_*.py` 并跑，所以退出码必须诚实）。

── 这个文件要证明的**不是**「代码能跑」────────────────────────────
是三条设计承诺真的成立，因为每一条都对应一种静默失败：

  1. **触顶必须停止并可观测。** 预算到顶后 `spend()` 抛异常而不是继续记账；
     跨过上限的那一笔要**带着消息**返回（说得出是哪条轴、为什么停）。
     若这条不成立，修复循环就会烧完 token 停在原地 —— 正是 ConWriter
     （arXiv 2608.05169）观察到的不收敛。
  2. **两条互斥建议打同一个字段 → conflicted，机器不挑边。**
     若这条不成立，机器就在替作者做裁决，而作者不会收到任何通知。
  3. **长度解耦是真的一等表达。** 默认作用域必须**不允许**改 `prose`
     这类长度字段 —— 若这条不成立，「不重跑字数约束」就只是口头约定。

时间全部注入 `now`，不 sleep、不碰真实时钟，因此每次跑结果完全一致。
提案一律用本地的 `P`（鸭子类型）构造，只在「与真实 `Diff` 互操作」那一节
用真的 `keel.ir.proposal.Diff` —— 那里要验的是**终态语义复用了既有的
`resolve()`，而不是本模块自己实现了一套**。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keel.ir.proposal import Diff, DiffStatus, resolve  # noqa: E402
from keel.pipeline.repair import (  # noqa: E402
    LENGTH_FIELDS,
    SCOPE_LENGTH,
    SCOPE_REPAIR,
    Conflict,
    RepairBudget,
    RepairBudgetExceeded,
    RepairScope,
    SpendOutcome,
    conflict_key,
    detect_conflicts,
    mark_conflicted,
)


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"  ✓ {label}")
        else:
            self.failed.append(label)
            print(f"  ✗ {label}" + (f"\n      {detail}" if detail else ""))

    def eq(self, got, want, label: str) -> None:
        self.ok(got == want, label, f"期望 {want!r}，实际 {got!r}")

    def group(self, name: str) -> None:
        print(f"\n── {name} ──")


#: 起点固定为 1000.0 秒；随后用 +N 秒表示「跑了 N 秒」。
T0 = 1000.0


@dataclass
class P:
    """鸭子类型的提案：只提供 `repair` 需要的五个属性。

    刻意**不用**真的 `Diff`：本模块承诺「不依赖 IR 具体类型」，那就得用
    一个不是 IR 类型的东西来验。真的 `Diff` 在第 6 节单独验（那里验的是
    终态语义的复用，不是鸭子类型）。
    """

    id: str
    target_card: str
    field: str
    after: Any
    status: DiffStatus = DiffStatus.PENDING
    before: Any = None


# ---------------------------------------------------------------------------
# 1. 预算三态：充足 / 边界 / 耗尽
# ---------------------------------------------------------------------------


def test_three_states(t: T) -> None:
    t.group("1. 预算三态（充足 / 边界 / 耗尽）")

    # 轮次
    b = RepairBudget(max_rounds=3)
    t.eq(b.exhausted(), [], "轮次 0/3 → 充足")
    b.rounds = 2
    t.eq(b.exhausted(), [], "轮次 2/3 → 仍能继续")
    b.rounds = 3
    t.eq(b.exhausted(), ["rounds"], "轮次 3/3 → 耗尽（第 4 轮不会开始）")
    b.rounds = 4
    t.eq(b.exhausted(), ["rounds"], "轮次 4/3 → 照停（如实报告）")

    # 字段改动数
    b = RepairBudget(max_field_edits=2)
    t.eq(b.exhausted(), [], "字段 0/2 → 充足")
    b.field_edits = 1
    t.eq(b.exhausted(), [], "字段 1/2 → 仍能继续")
    b.field_edits = 2
    t.eq(b.exhausted(), ["field_edits"], "字段 2/2 → 耗尽")

    # tokens
    b = RepairBudget(max_tokens=1000)
    b.tokens = 999
    t.eq(b.exhausted(), [], "tokens 999/1000 → 不停")
    b.tokens = 1000
    t.eq(b.exhausted(), ["tokens"], "tokens 1000/1000 → 停（>= 而非 >）")

    # 时长（10 分钟 = 600 秒）
    b = RepairBudget(max_minutes=10.0, started_at=T0)
    t.eq(b.exhausted(now=T0 + 599.0), [], "跑了 599 秒 → 不停")
    t.eq(b.exhausted(now=T0 + 600.0), ["minutes"], "跑了 600 秒（恰好 10 分钟）→ 停")

    # 上限为 0 = 一开始就停（0 >= 0）
    t.eq(
        RepairBudget(max_rounds=0).exhausted(),
        ["rounds"],
        "max_rounds=0 → 立刻停",
    )

    # None = 该轴不限（不是 0）
    empty = RepairBudget()
    empty.rounds = 10**9
    empty.field_edits = 10**9
    empty.tokens = 10**12
    t.eq(empty.exhausted(now=1e12), [], "全不限 + 天文数字用量 → 不跳")

    # 多轴同时触顶 → 全部报出，顺序固定
    b = RepairBudget(
        max_rounds=1, max_field_edits=1, max_tokens=1, max_minutes=1.0, started_at=T0
    )
    b.rounds = 9
    b.field_edits = 9
    b.tokens = 9
    t.eq(
        b.exhausted(now=T0 + 600.0),
        ["rounds", "field_edits", "tokens", "minutes"],
        "四条全超 → 四条全报，顺序固定",
    )


# ---------------------------------------------------------------------------
# 2. 触顶必须停止并可观测（不是继续跑，也不是只抛一句空话）
# ---------------------------------------------------------------------------


def test_hard_stop_is_observable(t: T) -> None:
    t.group("2. 触顶：停止 + 可观测（不是静默继续）")

    b = RepairBudget(max_rounds=2, started_at=T0)
    o1 = b.spend(rounds=1, now=T0 + 1.0)
    t.ok(isinstance(o1, SpendOutcome), "spend 返回 SpendOutcome")
    t.eq(o1.tripped, [], "第 1 轮后未触顶")
    t.ok(not o1.stopped, "第 1 轮后不该停")
    t.ok("修复继续" in o1.message, f"未触顶要写「修复继续」：{o1.message}")

    o2 = b.spend(rounds=1, now=T0 + 2.0)
    t.eq(o2.tripped, ["rounds"], "第 2 轮后触顶（额度用完）")
    t.ok(o2.stopped, "触顶即停")
    t.ok("修复预算到顶" in o2.message, f"触顶要写出来：{o2.message}")
    t.ok("轮次" in o2.message, f"说得出是哪条轴：{o2.message}")
    t.ok("不是故障" in o2.message, "明说这是正常停止（别被当成崩溃）")

    # 触顶之后再记账 = 静默继续 → 必须炸
    try:
        b.spend(rounds=1, now=T0 + 3.0)
        t.ok(False, "触顶后 spend 必须抛（否则就是静默继续）")
    except RepairBudgetExceeded as exc:
        t.ok(True, "触顶后 spend 抛 RepairBudgetExceeded")
        t.eq(exc.axes, ["rounds"], "异常携带触发的轴")
        t.ok("轮次" in str(exc), f"消息可读：{exc}")
    t.eq(b.rounds, 2, "被拒绝的那笔没有记进账（状态没被污染）")

    # guard() 是布尔路径之外的硬停入口，与 exhausted 判据一致
    b2 = RepairBudget(max_tokens=100, started_at=T0)
    b2.tokens = 100
    try:
        b2.guard(now=T0)
        t.ok(False, "到顶必须抛")
    except RepairBudgetExceeded as exc:
        t.eq(exc.axes, ["tokens"], "guard 抛的轴 == exhausted 的轴")
    t.ok(b2.should_stop(now=T0), "should_stop 与 guard 一致")

    # 三者判据一致：check/guard/should_stop/exhausted 是同一条判据
    top_rounds = RepairBudget(max_rounds=1, started_at=T0)
    top_rounds.rounds = 1
    cases = [
        ("空预算", RepairBudget(started_at=T0), T0 + 10**6),
        ("刚起步", RepairBudget(max_rounds=3, started_at=T0), T0 + 1.0),
        ("轮次到顶", top_rounds, T0 + 1.0),
        ("时长到顶", RepairBudget(max_minutes=1.0, started_at=T0), T0 + 60.0),
    ]
    for label, bb, now in cases:
        axes = bb.exhausted(now=now)
        raised = None
        try:
            bb.guard(now=now)
        except RepairBudgetExceeded as exc:
            raised = exc
        t.eq(bb.should_stop(now=now), bool(axes), f"{label}：should_stop 与 exceeded 一致")
        t.eq(raised is not None, bool(axes), f"{label}：guard 是否抛与 exceeded 一致")


# ---------------------------------------------------------------------------
# 3. 幂等
# ---------------------------------------------------------------------------


def test_idempotence(t: T) -> None:
    t.group("3. 幂等（重复调用不改变任何结论）")

    # 3a. 查询是纯函数：反复调用结果完全一致
    b = RepairBudget(max_rounds=3, max_field_edits=2, started_at=T0)
    b.rounds, b.field_edits, b.tokens = 1, 1, 500
    snap = (b.rounds, b.field_edits, b.tokens)
    r1 = (b.exhausted(now=T0 + 10), b.remaining(now=T0 + 10), b.render(now=T0 + 10))
    r2 = (b.exhausted(now=T0 + 10), b.remaining(now=T0 + 10), b.render(now=T0 + 10))
    t.eq(r1, r2, "exhausted / remaining / render 重复调用结果一致")
    t.eq((b.rounds, b.field_edits, b.tokens), snap, "查询不改动已用量")

    # 3b. 空记账是 no-op
    b0 = RepairBudget(max_rounds=3, started_at=T0)
    out = b0.spend(now=T0)
    t.eq((b0.rounds, b0.field_edits, b0.tokens), (0, 0, 0), "spend() 空记账不改状态")
    t.eq(out.tripped, [], "空记账不触顶")

    # 3c. 字段改动按 (卡, 字段) 去重：同一处来回复不重复计费
    b1 = RepairBudget(max_field_edits=5, started_at=T0)
    t.ok(b1.note_edit("scene:sc1", "outcome"), "第一次动 outcome → 计费")
    t.ok(not b1.note_edit("scene:sc1", "outcome"), "同一处再动 → 不重复计费（幂等）")
    t.eq(b1.field_edits, 1, "来回复三次也只算一处")
    t.ok(b1.note_edit("scene:sc1", "value"), "另一个字段 → 新计一笔")
    t.ok(b1.note_edit("scene:sc2", "outcome"), "另一张卡的同名字段 → 新计一笔")
    t.eq(b1.field_edits, 3, "波及面 = 3 处")
    t.eq(b1.exhausted(), [], "5 处额度用掉 3 处 → 未触顶")
    b1.note_edit("scene:sc3", "value")
    b1.note_edit("scene:sc4", "value")
    t.eq(b1.exhausted(), ["field_edits"], "5/5 → 触顶")

    # 3d. 冲突检测是纯函数，重复调用结果一致
    ps = [
        P("a", "scene:sc1", "outcome", "no_and"),
        P("b", "scene:sc1", "outcome", "yes_but"),
        P("c", "scene:sc2", "value", "信任"),
    ]
    t.eq(detect_conflicts(ps), detect_conflicts(ps), "detect_conflicts 幂等")
    t.eq(len(ps), 3, "检测不改输入长度")
    t.eq([p.status for p in ps], [DiffStatus.PENDING] * 3, "检测不改任何状态")

    # 3e. 标记冲突幂等：第二次不再返回已标记的提案（遥测不翻倍）
    t.eq(len(mark_conflicted(ps)), 2, "第一次标记 2 条")
    t.eq(mark_conflicted(ps), [], "第二次不再重复计入（终态幂等）")


# ---------------------------------------------------------------------------
# 4. 长度解耦：本轮修复不重跑字数约束
# ---------------------------------------------------------------------------


def test_length_decoupling(t: T) -> None:
    t.group("4. 长度解耦（修复轮不重跑字数约束）")

    t.ok("prose" in LENGTH_FIELDS, "prose 属于长度字段")
    t.ok(not SCOPE_REPAIR.allows("prose"), "默认作用域：不许改 prose")
    t.ok(not SCOPE_REPAIR.allows("target_words"), "默认作用域：不许改字数目标")
    t.ok(SCOPE_REPAIR.allows("outcome"), "默认作用域：结构字段照改")
    t.ok(SCOPE_LENGTH.allows("prose"), "显式打开长度 → 允许改 prose")

    # 黑名单硬于白名单：同一字段同时列入时听更硬的那个
    scope = RepairScope(allow_fields=frozenset({"prose"}), deny_fields=frozenset({"prose"}))
    t.ok(not scope.allows("prose"), "黑名单优先于白名单")
    t.ok(
        not RepairScope(enforce_length=True, allow_fields=frozenset({"outcome"})).allows("prose"),
        "白名单不含 prose → 不许改（即便开了长度）",
    )
    t.ok(
        RepairScope(enforce_length=True, allow_fields=frozenset({"prose"})).allows("prose"),
        "开了长度 + 白名单含 prose → 允许",
    )
    t.ok(
        not RepairScope(enforce_length=True, deny_fields=frozenset({"value"})).allows("value"),
        "黑名单命中 → 禁改",
    )

    # 作用域挂到预算上，预算是本轮唯一要传的对象
    b = RepairBudget(max_rounds=2, started_at=T0)
    t.ok(not b.allows("prose"), "预算默认作用域：不重跑字数")
    t.ok(RepairBudget(scope=SCOPE_LENGTH).allows("prose"), "换成 SCOPE_LENGTH → 允许")

    # render 必须让「不重跑字数」被**看见**，而不是只存在于调用方的记忆里
    line = b.render(now=T0)
    t.ok("本轮不重跑字数约束" in line, f"日志里写得不重跑字数：{line}")
    line = RepairBudget(scope=SCOPE_LENGTH, started_at=T0).render(now=T0)
    t.ok("本轮重跑字数约束" in line, f"日志里写明重跑字数：{line}")


# ---------------------------------------------------------------------------
# 5. 冲突检测：互斥 → conflicted；对称；自反
# ---------------------------------------------------------------------------


def test_conflict_detection(t: T) -> None:
    t.group("5. 冲突检测：互斥 / 对称 / 自反")

    # 5a. 两条互斥建议打同一个字段 → 必须产出冲突（本文件最要紧的一条）
    ps = [
        P("p1", "scene:sc3", "outcome", "no_and"),
        P("p2", "scene:sc3", "outcome", "yes_but"),
    ]
    cs = detect_conflicts(ps)
    t.eq(len(cs), 1, "两条互斥建议 → 1 处冲突")
    t.eq(cs[0].key, "scene:sc3::outcome", "冲突键 = 卡::字段")
    t.eq(cs[0].proposal_ids, ("p1", "p2"), "冲突含两条提案 id")
    t.eq(cs[0].values, ("no_and", "yes_but"), "冲突携带竞争值")

    # 5b. 对称：交换输入顺序，结果不变
    t.eq(detect_conflicts(list(reversed(ps))), cs, "反序输入 → 同一个冲突（对称）")

    # 5c. 自反：同一条建议传两次 ≠ 冲突
    t.eq(detect_conflicts([ps[0], ps[0]]), [], "同一条建议重复传入 → 不是冲突（自反）")
    t.eq(detect_conflicts([ps[0]]), [], "只有一条建议 → 不是冲突")

    # 5d. 值相同 = 两条建议其实一致 = 不是冲突
    same = [P("p1", "scene:sc3", "outcome", "no_and"), P("p2", "scene:sc3", "outcome", "no_and")]
    t.eq(detect_conflicts(same), [], "结论一致的两条建议 → 不是冲突")

    # 5e. 不同字段 / 不同卡 → 不冲突
    t.eq(
        detect_conflicts([P("p1", "scene:sc3", "outcome", "a"), P("p2", "scene:sc3", "value", "a")]),
        [],
        "不同字段 → 不冲突",
    )
    t.eq(
        detect_conflicts([P("p1", "scene:sc3", "outcome", "a"), P("p2", "scene:sc4", "outcome", "b")]),
        [],
        "不同卡 → 不冲突",
    )

    # 5f. 被拒绝的建议不参与（它已经被人否掉了，不改任何东西）
    rej = [
        P("p1", "scene:sc3", "outcome", "no_and"),
        P("p2", "scene:sc3", "outcome", "yes_but", status=DiffStatus.REJECTED),
    ]
    t.eq(detect_conflicts(rej), [], "已拒绝的建议不构成冲突")

    # 5g. 一处三方混战：三种值 → 一条冲突、三个 id（不是只报两个）
    three = [
        P("p1", "scene:sc1", "value", "信任"),
        P("p2", "scene:sc1", "value", "代价"),
        P("p3", "scene:sc1", "value", "真相"),
    ]
    cs = detect_conflicts(three)
    t.eq(len(cs), 1, "三方混战仍是**一处**冲突")
    t.eq(cs[0].proposal_ids, ("p1", "p2", "p3"), "三条互斥建议全在冲突里")
    t.eq(len(mark_conflicted(three)), 3, "参与冲突的提案**全部**标记，不只标记代表")

    # 5h. 两处冲突 → 报两处（不是只报第一处）
    two = [
        P("a1", "scene:sc1", "outcome", "x"),
        P("a2", "scene:sc1", "outcome", "y"),
        P("b1", "scene:sc2", "value", "x"),
        P("b2", "scene:sc2", "value", "y"),
    ]
    cs = detect_conflicts(two)
    t.eq(len(cs), 2, "两处互斥 → 报两处")
    t.eq([c.key for c in cs], ["scene:sc1::outcome", "scene:sc2::value"], "按 key 排序，顺序稳定")
    t.eq(conflict_key("scene:sc1", "outcome"), "scene:sc1::outcome", "conflict_key 拼接用 ::")

    # 5i. 冲突渲染出来是人话
    t.ok("互斥" in cs[0].render(), f"渲染说得出是互斥：{cs[0].render()}")
    t.ok("conflicted" in cs[0].render(), "渲染点明交人裁决")
    t.ok(isinstance(cs[0], Conflict), "返回的是 Conflict")


# ---------------------------------------------------------------------------
# 6. conflicted 是终态（且复用了 ir/proposal.py 既有的状态机）
# ---------------------------------------------------------------------------


def test_conflicted_is_terminal(t: T) -> None:
    t.group("6. conflicted 是终态（复用既有状态机，不新造）")

    ps = [
        P("p1", "scene:sc3", "outcome", "no_and"),
        P("p2", "scene:sc3", "outcome", "yes_but"),
    ]
    marked = mark_conflicted(ps)
    t.eq(len(marked), 2, "两条互斥建议都被标记")
    t.ok(
        all(p.status == DiffStatus.CONFLICTED for p in ps),
        "全部落为 conflicted（不是机器挑一条执行）",
    )
    # 不越权：不写 after、不写裁决元数据
    t.eq(ps[0].after, "no_and", "标记不改动 after（提案值原样保留）")
    t.eq(ps[1].after, "yes_but", "标记不改动另一个 after")

    # 再标一次：终态不翻转，也不重复计入
    t.eq(mark_conflicted(ps), [], "第二次标记 → 空（终态幂等）")
    t.ok(all(p.status == DiffStatus.CONFLICTED for p in ps), "仍是 conflicted，没被翻回去")

    # 已经被采纳的提案卷入冲突 → 反向裁决 → conflicted（与 proposal.resolve 同义）
    acc = [
        P("q1", "scene:sc9", "value", "信任", status=DiffStatus.ACCEPTED),
        P("q2", "scene:sc9", "value", "代价"),
    ]
    t.eq(len(mark_conflicted(acc)), 2, "已采纳的那条与待裁决的那条都被翻为 conflicted")
    t.ok(
        all(p.status == DiffStatus.CONFLICTED for p in acc),
        "accepted 与 pending 互斥 → 双双 conflicted",
    )

    # 与真实 Diff / resolve() 互操作：终态语义必须是**同一套**
    d1 = Diff(
        id="d1",
        target_card="scene:sc1",
        field="outcome",
        before="yes_but",
        after="no_and",
        rationale="结构需要",
        source_card="validator:outcome_distribution",
    )
    d2 = Diff(
        id="d2",
        target_card="scene:sc1",
        field="outcome",
        before="yes_but",
        after="yes_but",
        rationale="保持原样",
        source_card="validator:hook_cadence",
    )
    diffs = [d1, d2]
    cs = detect_conflicts(diffs)
    t.eq(len(cs), 1, "真实 Diff 上也能检出冲突（鸭子类型成立）")
    t.eq(mark_conflicted(diffs, conflicts=cs), [d1, d2], "真实 Diff 被标记")
    # 终态：再裁决不再翻转（resolve 的既有语义，本模块不另写一套）
    t.eq(
        resolve(diffs, "d1", DiffStatus.ACCEPTED).status,
        DiffStatus.CONFLICTED,
        "conflicted 后再 accept → 仍是 conflicted（终态）",
    )
    t.eq(
        resolve(diffs, "d2", DiffStatus.REJECTED).status,
        DiffStatus.CONFLICTED,
        "conflicted 后再 reject → 仍是 conflicted（终态）",
    )
    t.eq(d1.status, DiffStatus.CONFLICTED, "状态没有被翻回去")
    t.eq(d1.after, "no_and", "after 依然只是提案值，没被应用")


# ---------------------------------------------------------------------------
# 7. remaining / render：形状与确定性
# ---------------------------------------------------------------------------


def test_remaining_and_render(t: T) -> None:
    t.group("7. remaining / render：形状与确定性")

    b = RepairBudget(max_rounds=5, max_field_edits=4, max_tokens=5000, max_minutes=10.0,
                     started_at=T0)
    b.rounds, b.field_edits, b.tokens = 2, 1, 1200
    r = b.remaining(now=T0 + 180.0)  # 跑了 3 分钟
    t.eq(r["rounds"], 3, "还剩 3 轮")
    t.eq(r["field_edits"], 3, "还剩 3 处字段")
    t.eq(r["tokens"], 3800, "还剩 3800 tokens")
    t.eq(r["minutes"], 7.0, "还剩 7.0 分钟")
    t.eq(r["elapsed_minutes"], 3.0, "已跑 3.0 分钟")

    # 不限的轴 → None（不是 0、不是 inf）
    r = RepairBudget(started_at=T0).remaining(now=T0 + 180.0)
    t.eq(
        [r["rounds"], r["field_edits"], r["tokens"], r["minutes"]],
        [None, None, None, None],
        "不限的轴必须是 None（0 会被误读成「已用完」）",
    )
    t.eq(r["elapsed_minutes"], 3.0, "elapsed_minutes 恒有")

    # 零时零起点：不得除零 / nan / inf
    r0 = RepairBudget().remaining(now=0.0)
    t.eq(r0["elapsed_minutes"], 0.0, "零时零起点 → 0.0，不是除零")
    t.ok(all(v is None or v == v and abs(v) != float("inf") for v in r0.values()), "无 nan / inf")

    # 已超支 → 如实给负数（不是被夹到 0）
    over = RepairBudget(max_rounds=3, started_at=T0)
    over.rounds = 5
    t.eq(over.remaining(now=T0)["rounds"], -2, "超 2 轮 → -2")

    # render：单行、人话、说清还剩多少
    line = b.render(now=T0 + 180.0)
    t.ok(isinstance(line, str) and line.strip() != "", "非空字符串")
    t.ok("\n" not in line, "单行（无换行）")
    t.ok("修复继续" in line, "未到顶 → 开头写「修复继续」")
    t.ok("还剩 3 轮" in line, f"说清还剩几轮：{line}")
    t.ok("还剩 3800" in line, f"说清还剩多少 tokens：{line}")
    t.ok("还剩 7.0 分钟" in line, f"说清还剩多少时间：{line}")

    # 不限的轴写「不限」，不把 None 印给人类看
    line = RepairBudget(max_rounds=5, started_at=T0).render(now=T0)
    t.ok("不限" in line, f"不限的轴写「不限」：{line}")
    t.ok("None" not in line and "null" not in line, "不把 None 印给人类看")

    # 到顶：说得出为什么停 + 明说不是故障
    top = RepairBudget(max_rounds=1, max_field_edits=1, started_at=T0)
    top.rounds, top.field_edits = 1, 1
    line = top.render(now=T0)
    t.ok("修复预算到顶" in line, f"到顶要写出来：{line}")
    t.ok("轮次" in line and "字段改动" in line, f"说出是哪几条轴：{line}")
    t.ok("不是故障" in line, "明说这是正常停止")

    # 确定性：同一输入（注入 now）→ 同一输出
    t.eq(b.render(now=T0 + 180.0), b.render(now=T0 + 180.0), "同样输入 → 同样输出")
    # 同一个「相对已跑时长」，无论绝对时间取多少，结论一致
    for base in (0.0, 1e6, 1.7e9):
        bb = RepairBudget(max_minutes=10.0, started_at=base)
        t.eq(bb.exhausted(now=base + 599.0), [], f"base={base:g}：599 秒不停")
        t.eq(bb.exhausted(now=base + 600.0), ["minutes"], f"base={base:g}：600 秒停")
        t.eq(
            bb.remaining(now=base + 120.0)["minutes"],
            8.0,
            f"base={base:g}：已跑 2 分钟 → 剩 8.0",
        )


# ---------------------------------------------------------------------------
# 8. 变异护栏
# ---------------------------------------------------------------------------


def test_mutation_guards(t: T) -> None:
    t.group("8. 变异护栏（这些断言曾抓到实现被改坏）")

    # 变异 A：把 `>=` 改成 `>`（边界差一）—— 恰好用满额度时必须仍然停
    b = RepairBudget(max_rounds=3, started_at=T0)
    b.rounds = 3
    t.eq(b.exhausted(), ["rounds"], "用满 3 轮必须停（防 >= → >）")
    b = RepairBudget(max_tokens=1000, started_at=T0)
    b.tokens = 1000
    t.eq(b.exhausted(), ["tokens"], "用满 1000 tokens 必须停（防 >= → >）")

    # 变异 B：时间轴忘了乘 60（把分钟当秒）—— 10 分钟额度不能 10 秒就跳
    t.eq(
        RepairBudget(max_minutes=10.0, started_at=T0).exhausted(now=T0 + 10.0),
        [],
        "10 分钟额度下，10 秒不得跳（防漏 *60）",
    )

    # 变异 C：时间轴忘了减 started_at（直接拿 now 当 elapsed）
    t.eq(
        RepairBudget(max_minutes=10.0, started_at=T0).exhausted(now=T0 + 599.0),
        [],
        "elapsed 必须减去起点（防忽略 started_at）",
    )

    # 变异 D：多轴只报第一条（break / return 提前退出）
    d = RepairBudget(
        max_rounds=1, max_field_edits=1, max_tokens=1, max_minutes=1.0, started_at=T0
    )
    d.rounds, d.field_edits, d.tokens = 9, 9, 9
    t.eq(
        d.exhausted(now=T0 + 600.0),
        ["rounds", "field_edits", "tokens", "minutes"],
        "四条都超必须报四条（防只报第一条）",
    )

    # 变异 E：把不限的轴当成 0 处理 → 一开局就停
    t.ok(
        not RepairBudget(started_at=T0).should_stop(now=T0),
        "空预算开局不得停（防 None 被当 0）",
    )
    fresh = RepairBudget(max_rounds=3, started_at=T0)
    t.eq(fresh.spend(rounds=1, now=T0).tripped, [], "空额度开局照常可记一笔")

    # 变异 F：触顶后 spend 变成「静默记一笔」（最危险的一种改坏）
    b = RepairBudget(max_rounds=1, started_at=T0)
    t.ok(b.spend(rounds=1, now=T0).stopped, "用满额度那一笔要报告触顶")
    try:
        b.spend(rounds=1, now=T0)
        t.ok(False, "触顶后 spend 必须抛（防静默继续）")
    except RepairBudgetExceeded:
        t.ok(True, "触顶后 spend 抛（防静默继续）")

    # 变异 G：冲突检测漏掉同组第二条（只挑第一条建议，永远检不出冲突）
    t.eq(
        len(
            detect_conflicts(
                [
                    P("p1", "scene:sc1", "outcome", "x"),
                    P("p2", "scene:sc1", "outcome", "y"),
                ]
            )
        ),
        1,
        "同字段不同值必须检出冲突（防只取第一条）",
    )

    # 变异 H：把「值相同」当成冲突（忘了比较 after）→ 一致的建议被误报
    t.eq(
        detect_conflicts(
            [
                P("p1", "scene:sc1", "outcome", "x"),
                P("p2", "scene:sc1", "outcome", "x"),
            ]
        ),
        [],
        "结论相同的两条建议不得误报为冲突（防漏比 after）",
    )

    # 变异 I：把已拒绝的建议也算进冲突（人否掉的东西不该再排队）
    t.eq(
        detect_conflicts(
            [
                P("p1", "scene:sc1", "outcome", "x"),
                P("p2", "scene:sc1", "outcome", "y", status=DiffStatus.REJECTED),
            ]
        ),
        [],
        "已拒绝的建议不参与冲突（防漏查 status）",
    )
    rejected = P("r", "scene:sc1", "outcome", "y", status=DiffStatus.REJECTED)
    mark_conflicted(
        [P("p1", "scene:sc1", "outcome", "x"), rejected],
        conflicts=[Conflict("scene:sc1", "outcome", ("p1",), ("x",))],
    )
    t.eq(rejected.status, DiffStatus.REJECTED, "标记冲突时不得翻动已拒绝的提案")

    # 变异 J：长度解耦被默认打开（那等于没解耦）
    t.ok(not SCOPE_REPAIR.allows("prose"), "默认作用域不许改长度字段（防默认改成 True）")
    t.ok(SCOPE_REPAIR.enforce_length is False, "SCOPE_REPAIR 的 enforce_length 必须是 False")

    # 变异 K：字段改动按次数计费（来回复会更快触顶，掩盖不收敛信号）
    b = RepairBudget(max_field_edits=3, started_at=T0)
    for _ in range(10):
        b.note_edit("scene:sc1", "outcome")
    t.eq(b.field_edits, 1, "同一处来回复 10 次仍只算 1 处（防按次数计费）")
    t.eq(b.exhausted(), [], "来回复不该烧掉字段轴（那是 rounds 轴的职责）")


def main() -> int:
    t = T()
    print("═" * 64)
    print("  修复预算与冲突消解（repair）—— 三态 / 硬停 / 幂等 / 冲突 / 长度解耦")
    print("═" * 64)
    test_three_states(t)
    test_hard_stop_is_observable(t)
    test_idempotence(t)
    test_length_decoupling(t)
    test_conflict_detection(t)
    test_conflicted_is_terminal(t)
    test_remaining_and_render(t)
    test_mutation_guards(t)

    print("\n" + "─" * 64)
    print(f"  通过 {t.passed} · 失败 {len(t.failed)}")
    if t.failed:
        for f in t.failed:
            print(f"    ✗ {f}")
        return 1
    print("  全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
