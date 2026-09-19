"""全局漂移门禁（`keel/validators/drift.py`）的单元测试（含变异测试）。

跑法：
    .venv/Scripts/python.exe tests/test_drift.py

零依赖（不用 pytest），与 `tests/test_workbuddy_gen.py` 同风格。

── 为什么要单独测它 ─────────────────────────────────────────────

它是**唯一一个尾窗（累积）口径**的门禁，而它的两类失败都是静默的：

  1. **恒不触发** —— 窗口切不出来、论点面算不出来、前段永远为空，
     它就永远返回 []。「干净基线全绿」与「它一次都没判过」会同时成立，
     这正是本项目反复踩的坑（`li_yu_reduce_threads` 曾因窗口 <4 而数学上
     不可能触发）。故每一条判据都必须有自己的**反例**：不报警的那一侧
     必须证明「判据在动」，而不是「判据睡着了」。
  2. **恒触发** —— 反过来，若它对一个正常故事乱报警，自主运行每跑几场
     就被暂停一次，门禁会立刻被关掉。故也有「不该报」的一侧。

反例 IR 全部在**本文件**里构造（不动 `tests/fixtures.py`）：
共享 fixture 是集成方串行编辑的文件，往里塞东西会与别人的改动互踩。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keel.ir.enums import ArcShape, SceneOutcome, Severity  # noqa: E402
from keel.ir.models import (  # noqa: E402
    Commitment,
    CommitmentLayer,
    NarrativeIR,
    SceneNode,
    StateDelta,
    TimePoint,
)
from keel.validators import drift  # noqa: E402
from keel.validators.drift import drift_guard  # noqa: E402


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


# ---------------------------------------------------------------------------
# IR 构造
# ---------------------------------------------------------------------------

#: 控制理念。字面措辞必须与「在论点上」的场景卡共享字符二元组 ——
#: 本门禁是**字面**判据，这一点在测试里不能含糊。
_THESIS = "交付信任才会被接住"

#: 漂移段用的词汇：与 _THESIS 的字符集（交/付/信/任/才/会/被/接/住）**完全不相交**，
#: 于是字符二元组交集必然为空 —— 这是构造零重叠的可靠办法，不是碰运气。
_WANDER = "雪山", "渡口", "刀谱", "旧账", "清点", "错漏"


def _scene(
    idx: int,
    *,
    value: str,
    tp: str,
    conflict: str = "挡在前面的是旧习惯",
    goal: str = "他要拿到一个答案",
    start: str = "+",
    end: str = "-",
    attrs: tuple[tuple[str, str], ...] = (),
    outcome: SceneOutcome = SceneOutcome.YES_BUT,
) -> SceneNode:
    return SceneNode(
        id=f"s{idx}",
        title=f"第 {idx} 场",
        focalizer="protagonist",
        narrator="narrator",
        fabula_time=TimePoint(day=idx),
        sjuzhet_index=idx - 1,
        value=value,
        value_charge_start=start,
        value_charge_end=end,
        goal=goal,
        conflict=conflict,
        turning_point=tp,
        outcome=outcome,
        state_deltas=[
            StateDelta(entity_id=e, attribute=a, before=False, after=True)
            for e, a in attrs
        ],
    )


def _ir(scenes: list[SceneNode], *, open_commitments: tuple[str, ...] = ()) -> NarrativeIR:
    return NarrativeIR(
        title="漂移测试",
        commitment=CommitmentLayer(
            premise=_THESIS,
            controlling_idea=_THESIS,
            logline="一句话",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="他交出刀",
            commitments=[
                Commitment(
                    id=f"c{i}",
                    kind="theme",
                    statement=stmt,
                    severity=Severity.WARN,
                )
                for i, stmt in enumerate(open_commitments)
            ],
        ),
        scenes=scenes,
    )


def _kinds(fs: list) -> list[str]:
    return [f.evidence.get("kind", "?") for f in fs]


# ---------------------------------------------------------------------------
# 1. 在论点上、且在推进 —— 不报警
# ---------------------------------------------------------------------------


def test_coherent_run(t: T) -> None:
    print("\n── 1. 正常长跑：不报警 ──")
    # 6 场：每场一个新状态键、一个新的价值-极性走向，且**每场**都碰到论点词汇。
    scenes = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="信任", tp="交付之后他等着被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(3, value="交付", tp="信任被退回，他重新权衡", start="+", end="-",
               attrs=(("protagonist", "权衡"),)),
        _scene(4, value="交付", tp="他把刀交付出去", start="-", end="+",
               attrs=(("counterpart", "接住"),)),
        _scene(5, value="依靠", tp="接住他的人提出条件", start="+", end="-",
               attrs=(("protagonist", "依靠"),)),
        _scene(6, value="依靠", tp="最后一次交付与接住", start="-", end="+",
               attrs=(("counterpart", "同行"),)),
    ]
    fs = drift_guard(_ir(scenes))
    t.eq(fs, [], "在论点上且持续推进的运行：零告警")
    t.eq(drift_guard(_ir(scenes, open_commitments=("交付必须付出代价",))), [],
         "带未兑现承诺仍不报警（承诺未兑现不等于已经漂移）")


# ---------------------------------------------------------------------------
# 2. 论点漂移 —— 报警
# ---------------------------------------------------------------------------


def test_thesis_drift(t: T) -> None:
    print("\n── 2. 论点漂移：前段在论点上、尾窗完全不碰 ──")
    scenes = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="信任", tp="交付之后他等着被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(3, value="交付", tp="信任被退回，他重新权衡", start="+", end="-",
               attrs=(("protagonist", "权衡"),)),
        # ── 以下三场：词汇与论点面完全不相交（雪山/渡口/刀谱/旧账…）──
        _scene(4, value="旧账", tp=f"他在{_WANDER[0]}下清点{_WANDER[3]}", start="-", end="+",
               attrs=(("protagonist", "旧账"),)),
        _scene(5, value="刀谱", tp=f"{_WANDER[2]}的{_WANDER[5]}被翻出来", start="+", end="-",
               attrs=(("counterpart", "刀谱"),)),
        _scene(6, value="渡口", tp=f"{_WANDER[1]}的船期提前", start="-", end="+",
               attrs=(("protagonist", "渡口"),)),
    ]
    fs = drift_guard(_ir(scenes))
    t.eq(len(fs), 1, "只产出一条（漂移），不夹带原地踏步")
    t.eq(_kinds(fs), ["thesis_drift"], "告警类型是 thesis_drift")
    if fs:
        f = fs[0]
        t.ok(f.severity is Severity.WARN, "严重度是 WARN（按约定：暂停自主运行）")
        t.ok(bool(f.suggestion), "带 suggestion（契约：每条 Finding 都要有）")
        t.eq(f.code, "drift_guard", "code 是 drift_guard")
        t.eq(f.scene_id, "s6", "定位在尾窗最后一场（人在那里接手）")
        t.eq(f.evidence["window_hits"], 0, "尾窗命中 0")
        t.ok(f.evidence["early_hits"] > 0, "前段命中 > 0（是**漂移**，不是从未锚定）")
        t.eq(f.evidence["window_scene_ids"], ["s4", "s5", "s6"], "尾窗场次写进 evidence")


def test_open_commitment_is_thesis(t: T) -> None:
    print("\n── 2b. 未兑现的承诺也算论点面 ──")
    # 控制理念**从未**出现在任何一场（故它单独不构成「前段命中」）；
    # 论点面里剩下的那一半 —— 未兑现的承诺 —— 才是判据的来源。
    # 前段只用「刀谱 / 旧账 / 渡口」，尾窗只用「雪山 / 脚印 / 清点 / 错漏」
    # —— 两组词汇的字符二元组不相交，重叠为空是**构造**出来的，不是碰运气。
    scenes = [
        _scene(1, value="刀谱", tp="他在渡口翻看刀谱", start="+", end="-",
               attrs=(("protagonist", "刀谱"),)),
        _scene(2, value="旧账", tp="旧账的最后一行被划掉", start="-", end="+",
               attrs=(("protagonist", "旧账"),)),
        _scene(3, value="刀谱", tp="渡口有人认出那本刀谱", start="+", end="-",
               attrs=(("protagonist", "认出"),)),
        _scene(4, value="雪山", tp="雪山上的脚印断了", start="-", end="+",
               attrs=(("counterpart", "脚印"),)),
        _scene(5, value="清点", tp="重新清点一遍行李", start="+", end="-",
               attrs=(("protagonist", "清点"),)),
        _scene(6, value="错漏", tp="错漏出现在最后一页", start="-", end="+",
               attrs=(("counterpart", "错漏"),)),
    ]
    # 未兑现的承诺措辞 = 前段场景的词汇（刀谱/旧账）
    fs_open = drift_guard(_ir(scenes, open_commitments=(f"{_WANDER[2]}与{_WANDER[3]}",)))
    t.eq(_kinds(fs_open), ["thesis_drift"], "前段碰过未兑现承诺、尾窗完全不碰 → 漂移")

    # 同一份 IR，只是把承诺标成已兑现：它就**退出**论点面，
    # 于是论点面只剩从未出现的控制理念 → 前段命中 0 → 不可判（返回 []）。
    ir_done = _ir(scenes, open_commitments=(f"{_WANDER[2]}与{_WANDER[3]}",))
    # 「已兑现」由 IR 的 `satisfied` 标记**声明**，不再由词法现场判定 ——
    # 主题兑现不可机判（见 structure.commitment_satisfied 的 docstring）。
    ir_done.commitment.commitments[0].satisfied = True
    t.eq(drift_guard(ir_done), [], "已兑现的承诺退出论点面（不再需要推进）")


# ---------------------------------------------------------------------------
# 3. 原地踏步 —— 报警
# ---------------------------------------------------------------------------


def test_padding_no_new_ground(t: T) -> None:
    print("\n── 3. 原地踏步：尾窗只把旧变量拨回原处 ──")
    # 每场都有状态增量、都翻转价值（逐场检查全绿），
    # 但三场用的全是前段已经用过的状态键与价值走向 —— 净推进为零。
    head = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="交付", tp="交付之后他等着被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(3, value="依靠", tp="接住他的人提出条件", start="+", end="-",
               attrs=(("protagonist", "依靠"),)),
    ]
    tail = [
        _scene(4, value="信任", tp="他再次试着交付信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(5, value="交付", tp="再一次交付，等待被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(6, value="依靠", tp="接住之后还是那个条件", start="+", end="-",
               attrs=(("protagonist", "依靠"),)),
    ]
    fs = drift_guard(_ir(head + tail))
    t.eq(len(fs), 1, "只产出一条（原地踏步），不夹带漂移")
    t.eq(_kinds(fs), ["padding"], "告警类型是 padding")
    if fs:
        f = fs[0]
        t.ok(f.severity is Severity.WARN, "严重度是 WARN")
        t.ok(bool(f.suggestion), "带 suggestion")
        t.eq(f.evidence["reason"], "no_new_ground", "理由：没有新地面")
        t.eq(f.evidence["new_delta_keys"], [], "新状态键 0 个")
        t.eq(f.evidence["new_transitions"], [], "新的价值-极性走向 0 个")
        # 关键：逐场口径在这里**全绿** —— 这正是「每段都合理、合起来什么都不证明」
        t.ok(all(s.state_deltas for s in tail), "尾窗每场都有状态增量（逐场检查会放行）")
        t.ok(all(s.value_flips for s in tail), "尾窗每场都翻转价值（逐场检查会放行）")


def test_padding_flat_window(t: T) -> None:
    print("\n── 3b. 原地踏步：整段既无状态增量也无价值翻转 ──")
    head = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="交付", tp="交付之后他等着被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(3, value="依靠", tp="接住他的人提出条件", start="+", end="-",
               attrs=(("protagonist", "依靠"),)),
    ]
    # 三场静场：无状态增量、价值不翻转（start == end），措辞仍在论点上
    tail = [
        _scene(4, value="信任", tp="他反复掂量要不要交付信任", start="+", end="+"),
        _scene(5, value="信任", tp="接住与不接住的两种可能", start="+", end="+"),
        _scene(6, value="信任", tp="交付的念头又被压下去", start="+", end="+"),
    ]
    fs = drift_guard(_ir(head + tail))
    t.eq(_kinds(fs), ["padding"], "死水窗口报 padding")
    if fs:
        t.eq(fs[0].evidence["reason"], "flat_window", "理由：整段是死水")
        t.eq(fs[0].evidence["window_delta_count"], 0, "窗口状态增量 0")
        t.eq(fs[0].evidence["window_flip_count"], 0, "窗口价值翻转 0")
        t.ok(bool(fs[0].suggestion), "带 suggestion")


# ---------------------------------------------------------------------------
# 4. 运行太短 —— 不判（返回 []，而不是判「没问题」）
# ---------------------------------------------------------------------------


def test_too_short(t: T) -> None:
    print("\n── 4. 运行太短：没有可比前段，不判 ──")
    for n in (0, 1, 2, 3):
        scenes = [
            _scene(i, value="信任", tp="他试着交付一点信任",
                   start="+", end="-", attrs=(("protagonist", f"attr{i}"),))
            for i in range(1, n + 1)
        ]
        t.eq(drift_guard(_ir(scenes)), [], f"{n} 场：窗口切不出来 → 返回 []")

    # 4 场是第一条可评估的长度（尾窗 3 + 前段 1）：只有第 1 场在论点上
    four = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="旧账", tp=f"他在{_WANDER[0]}下清点{_WANDER[3]}", start="-", end="+",
               attrs=(("protagonist", "旧账"),)),
        _scene(3, value="刀谱", tp=f"{_WANDER[2]}的{_WANDER[5]}被翻出来", start="+", end="-",
               attrs=(("protagonist", "刀谱"),)),
        _scene(4, value="渡口", tp=f"{_WANDER[1]}的船期提前", start="-", end="+",
               attrs=(("protagonist", "渡口"),)),
    ]
    t.eq(_kinds(drift_guard(_ir(four))), ["thesis_drift"], "4 场即已可评估（尾窗 3 + 前段 1）")

    # 没有论点面（控制理念为空、无承诺）也不可判 —— 不是「判过了没问题」
    empty = _ir(four)
    empty.commitment.controlling_idea = ""
    t.eq(drift_guard(empty), [], "论点面为空：不可判，返回 []")


# ---------------------------------------------------------------------------
# 5. 变异：判据必须是承重的，不是摆设
# ---------------------------------------------------------------------------


def test_mutation(t: T) -> None:
    print("\n── 5. 变异：拆掉判据，对应的告警必须消失 ──")
    scenes_drift = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="信任", tp="交付之后他等着被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(3, value="交付", tp="信任被退回，他重新权衡", start="+", end="-",
               attrs=(("protagonist", "权衡"),)),
        _scene(4, value="旧账", tp=f"他在{_WANDER[0]}下清点{_WANDER[3]}", start="-", end="+",
               attrs=(("protagonist", "旧账"),)),
        _scene(5, value="刀谱", tp=f"{_WANDER[2]}的{_WANDER[5]}被翻出来", start="+", end="-",
               attrs=(("counterpart", "刀谱"),)),
        _scene(6, value="渡口", tp=f"{_WANDER[1]}的船期提前", start="-", end="+",
               attrs=(("protagonist", "渡口"),)),
    ]
    scenes_pad = [
        _scene(1, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(2, value="交付", tp="交付之后他等着被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(3, value="依靠", tp="接住他的人提出条件", start="+", end="-",
               attrs=(("protagonist", "依靠"),)),
        _scene(4, value="信任", tp="他再次试着交付信任", start="+", end="-",
               attrs=(("protagonist", "信任"),)),
        _scene(5, value="交付", tp="再一次交付，等待被接住", start="-", end="+",
               attrs=(("protagonist", "交付"),)),
        _scene(6, value="依靠", tp="接住之后还是那个条件", start="+", end="-",
               attrs=(("protagonist", "依靠"),)),
    ]
    ir_drift, ir_pad = _ir(scenes_drift), _ir(scenes_pad)
    t.ok(_kinds(drift_guard(ir_drift)) == ["thesis_drift"], "（前置）漂移 IR 正常报")
    t.ok(_kinds(drift_guard(ir_pad)) == ["padding"], "（前置）空转 IR 正常报")

    # 变异 1：论点面算不出来（返回空集）—— 漂移告警必须消失
    orig = drift._thesis_grams
    drift._thesis_grams = lambda ir: set()
    try:
        t.eq(_kinds(drift_guard(ir_drift)), [], "变异：论点面置空 → 漂移告警消失")
    finally:
        drift._thesis_grams = orig
    t.eq(_kinds(drift_guard(ir_drift)), ["thesis_drift"], "还原后恢复（变异是可逆的）")

    # 变异 2：窗口切不出来 —— 两条判据都必须失声（证明它们**都**走尾窗）
    orig_w = drift._trailing_window
    drift._trailing_window = lambda scenes: ([], [])
    try:
        t.eq(drift_guard(ir_drift), [], "变异：无尾窗 → 漂移不报")
        t.eq(drift_guard(ir_pad), [], "变异：无尾窗 → 空转不报")
    finally:
        drift._trailing_window = orig_w
    t.eq(_kinds(drift_guard(ir_pad)), ["padding"], "还原后恢复")

    # 变异 3：状态键永远算成「新地面」（每次调用给一个没见过的键）
    # —— 空转告警必须消失，证明它真的在数 new_keys，而不是恒真。
    counter = iter(range(10**6))
    orig_k = drift._delta_keys
    drift._delta_keys = lambda s: {("mut", str(next(counter)))}
    try:
        t.eq(_kinds(drift_guard(ir_pad)), [], "变异：状态键恒为新 → 空转告警消失")
    finally:
        drift._delta_keys = orig_k
    t.eq(_kinds(drift_guard(ir_pad)), ["padding"], "还原后恢复")


# ---------------------------------------------------------------------------
# 6. 契约：本模块不注册自己（集成方负责注册）
# ---------------------------------------------------------------------------


def test_contract(t: T) -> None:
    print("\n── 6. 契约 ──")
    import inspect

    src = inspect.getsource(drift)
    # 集成方已在 base.py::REQUIRES 登记并完成注册，故这里断言**已注册**且在表里。
    # （原先断言「不含 @register」是派发期的临时契约 —— 那时注册还没做，
    #   断言它没被注册是为了防止代理越界改共享表。注册完成后该断言必须翻转，
    #   否则它会永远挡着「已注册」这个正确状态。）
    t.ok("@register" in src, "模块已 @register（集成方已完成注册）")
    from keel.validators.base import REQUIRES, available

    t.ok("drift_guard" in available(), "drift_guard 已进入 registry")
    t.ok(
        "drift_guard" in REQUIRES,
        "drift_guard 已在 REQUIRES 声明数据需求（铁律 15：缺它会被判死门禁）",
    )
    t.ok("Severity.WARN" in src, "源码含 WARN 严重度（它是门禁，不是读数项）")
    scenes = [
        _scene(i, value="信任", tp="他试着交付一点信任", start="+", end="-",
               attrs=(("protagonist", f"a{i}"),))
        for i in range(1, 7)
    ]
    fs = drift_guard(_ir(scenes))
    t.ok(isinstance(fs, list), "返回 list")
    for f in fs:
        t.ok(f.suggestion is not None, f"{f.code} 带 suggestion")
        t.ok(isinstance(f.evidence, dict) and f.evidence, f"{f.code} 带 evidence")


def main() -> int:
    t = T()
    print("═" * 64)
    print("  全局漂移门禁 drift_guard —— 论点漂移 / 原地踏步 / 变异")
    print("═" * 64)
    test_coherent_run(t)
    test_thesis_drift(t)
    test_open_commitment_is_thesis(t)
    test_padding_no_new_ground(t)
    test_padding_flat_window(t)
    test_too_short(t)
    test_mutation(t)
    test_contract(t)

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
