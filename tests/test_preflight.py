"""自主运行前计划门禁（preflight）的单元测试 + 变异测试。

跑法：
    .venv/Scripts/python.exe tests/test_preflight.py

零依赖（不用 pytest），与 `tests/test_workbuddy_gen.py` 同风格。

── 这个测试要证明的四件事 ───────────────────────────────────────

1. **弱计划会被拦住**，而且**每条检查各自独立地**会响 ——
   不是「有一个大检查响就等于全响了」。做法：从一份好计划出发，
   每次只弄坏一样东西，断言只有对应的那个 check id 报警。
   少了这一步，五条检查退化成一条也能全绿。
2. **好计划静默** —— 干净计划上 `ok=True` 且零阻断零警告。
   这是防「对着任何东西都报警」的伪命中（本项目一贯的净命中口径）。
3. **不崩** —— 空场景列表、空角色表、空字符串，一律是结论，不是异常。
   本模块按设计**根本不读 `ir.scenes`**，空场景是它的正常工况。
4. **每条阻断项都带 suggestion** —— 没有 actionable 建议的阻断是耍流氓。

── 关于第 5 节「变异」 ─────────────────────────────────────────

变异不写在测试里（那样它永远绿），而是**手动改实现、跑、确认变红、还原**。
本文件跑完后执行的变异与结果见 `main()` 末尾的打印与交付报告。
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.ir.enums import ArcShape, Severity  # noqa: E402
from loom.ir.models import (  # noqa: E402
    Character,
    Commitment,
    CommitmentLayer,
    NarrativeIR,
)
from loom.pipeline.preflight import (  # noqa: E402
    CHECK_IDS,
    PreflightError,
    assert_ready,
    preflight,
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


# ---------------------------------------------------------------------------
# IR 构造（本文件自建，不动 tests/fixtures.py —— 那是集成方的地盘）
# ---------------------------------------------------------------------------

_GOOD_PREMISE = "偏执地独自承担一切，会把最该信任的人推成敌人。"
_GOOD_ANCHOR = "他把刀留在雪地里，转身走进风雪"
_GOOD_IDEA = "真正的背叛不是被出卖，而是从未允许别人靠近。"


def _commitment(
    premise: str = _GOOD_PREMISE,
    ending_anchor: str = _GOOD_ANCHOR,
    controlling_idea: str = _GOOD_IDEA,
    commitments: list[Commitment] | None = None,
) -> CommitmentLayer:
    if commitments is None:
        commitments = [
            Commitment(
                id="c-ending",
                kind="ending",
                statement="结局必须落在他独自离开的那一步",
                must_hold_at=["s-last"],
            ),
            Commitment(
                id="c-theme",
                kind="theme",
                statement="中段至少一次把信任交出去的机会被他自己毁掉",
                must_hold_at=["s-03"],
            ),
        ]
    return CommitmentLayer(
        premise=premise,
        controlling_idea=controlling_idea,
        logline="一个不敢信人的刀客，最后把刀留在雪地里",
        arc_shape=ArcShape.MAN_IN_A_HOLE,
        ending_anchor=ending_anchor,
        commitments=commitments,
    )


def _ir(
    *,
    premise: str = _GOOD_PREMISE,
    ending_anchor: str = _GOOD_ANCHOR,
    controlling_idea: str = _GOOD_IDEA,
    commitments: list[Commitment] | None = None,
    characters: list[Character] | None = None,
    scenes: list | None = None,
) -> NarrativeIR:
    """默认是一份**好计划**；要弄坏哪一样就传哪一样。"""
    if characters is None:
        characters = [
            Character(
                id="ch-1",
                name="林砚",
                want="把名单上的人全部清掉",
                need="允许自己被别人接住一次",
                flaw="从不求助",
                arc_from="独行",
                arc_to="交出刀",
            )
        ]
    ir = NarrativeIR(
        title="断云崖",
        commitment=_commitment(
            premise=premise,
            ending_anchor=ending_anchor,
            controlling_idea=controlling_idea,
            commitments=commitments,
        ),
        scenes=list(scenes or []),
    )
    for c in characters:
        ir.characters.add(c)
    return ir


def _checks(findings: list) -> set[str]:
    return {f.evidence.get("check") for f in findings}


# ---------------------------------------------------------------------------
# 1. 好计划静默
# ---------------------------------------------------------------------------


def test_good_plan_silent(t: T) -> None:
    print("\n── 1. 好计划：静默放行 ──")
    r = preflight(_ir())
    t.ok(r.ok, "好计划 ok=True")
    t.eq(len(r.blockers), 0, "好计划没有阻断项")
    t.eq(len(r.warnings), 0, "好计划没有警告项")
    t.eq(r.checks_run, len(CHECK_IDS), f"checks_run == {len(CHECK_IDS)}（全部检查都跑了）")

    # assert_ready 在好计划上必须**什么都不做**
    try:
        assert_ready(_ir())
        t.ok(True, "assert_ready 在好计划上不抛异常")
    except PreflightError as exc:
        t.ok(False, "assert_ready 在好计划上不抛异常", str(exc))


# ---------------------------------------------------------------------------
# 2. 弱 / 空计划：四条阻断 + 一条警告，各自独立
# ---------------------------------------------------------------------------


def test_empty_plan(t: T) -> None:
    print("\n── 2. 空计划：四条阻断 + 一条警告 ──")
    empty = _ir(
        premise="",
        ending_anchor="",
        controlling_idea="",
        commitments=[],
        characters=[],
    )
    r = preflight(empty)
    t.ok(not r.ok, "空计划 ok=False")
    t.eq(
        _checks(r.blockers),
        {"ending_anchor", "premise", "commitment", "controlling_idea"},
        "四条阻断项各自独立响起",
    )
    t.eq(_checks(r.warnings), {"character_need"}, "character_need 是警告项")
    t.eq(r.checks_run, len(CHECK_IDS), "空计划也跑完全部检查（缺失是结论，不是「没测」）")


def test_each_check_fires_alone(t: T) -> None:
    print("\n── 3. 每次只弄坏一样：只有对应的检查响 ──")

    # (标签, 改动, 期望 check id, 期望 reason) —— 断言 reason 而不只是 check id：
    # 「报了同一条」也可能是另一条分支误伤，只有 reason 能证明是**那一条判据**在响。
    cases: list[tuple[str, dict, str, str]] = [
        ("结局锚点为空", {"ending_anchor": ""}, "ending_anchor", "empty"),
        ("结局锚点是纯情绪", {"ending_anchor": "释然"}, "ending_anchor", "emotion_only"),
        (
            "结局锚点是纯情绪（长一点）",
            {"ending_anchor": "他终于释然与和解了"},
            "ending_anchor",
            "emotion_only",
        ),
        ("前提为空", {"premise": ""}, "premise", "empty"),
        (
            "前提是主题词（提示词点名的反例）",
            {"premise": "关于信任"},
            "premise",
            "topic_marker",
        ),
        ("前提是光秃秃一个词", {"premise": "信任"}, "premise", "no_causal_marker"),
        ("控制理念为空", {"controlling_idea": ""}, "controlling_idea", "empty"),
    ]
    for label, kwargs, want, reason in cases:
        r = preflight(_ir(**kwargs))
        t.eq(_checks(r.blockers), {want}, f"{label} → 只报 {want}")
        t.eq(len(r.blockers), 1, f"{label} → 恰好一条阻断项")
        t.eq(r.blockers[0].evidence.get("reason"), reason, f"{label} → reason={reason}")
        t.ok(not r.ok, f"{label} → ok=False")

    # -- 承诺层的四种坏法（都在同一个 check id 下，靠 reason 区分）--
    r = preflight(_ir(commitments=[]))
    t.eq(_checks(r.blockers), {"commitment"}, "承诺层为空 → 只报 commitment")
    t.eq(r.blockers[0].evidence.get("reason"), "empty", "reason=empty")

    all_done = [
        Commitment(id="c1", kind="ending", statement="已兑现", must_hold_at=["s-1"], satisfied=True)
    ]
    r = preflight(_ir(commitments=all_done))
    t.eq(_checks(r.blockers), {"commitment"}, "承诺全部兑现 → 只报 commitment")
    t.eq(r.blockers[0].evidence.get("reason"), "all_satisfied", "reason=all_satisfied")

    no_anchor = [
        Commitment(id="c1", kind="ending", statement="没落点", must_hold_at=[])
    ]
    r = preflight(_ir(commitments=no_anchor))
    t.eq(_checks(r.blockers), {"commitment"}, "未兑现承诺没有 must_hold_at → 只报 commitment")
    t.eq(r.blockers[0].evidence.get("reason"), "no_anchor", "reason=no_anchor")

    # 「有分句、无因果标记」视为断言结构成立 —— 两个分句并置本身就在
    # 陈述一个关系（这是本模块「宁漏报不误报」取舍的一部分，故显式断言住）。
    # 少了这条断言，「分句标点不再算证据」这个变异会存活。
    r = preflight(_ir(premise="他独自承担一切，最信任的人站到了对面"))
    t.ok(r.ok, "有分句、无因果标记的前提仍视为断言（不误报）")

    # 词表不许有重复项：重复项会让「删掉某一项」的变异测不出来。
    from loom.pipeline import preflight as _pf

    t.eq(
        len(_pf._EMOTION_TERMS), len(set(_pf._EMOTION_TERMS)), "情绪词表无重复项"
    )

    # 变异杀手：已兑现的承诺**有**落点、未兑现的**没有**落点。
    # 若实现错把「全部承诺」当成「未兑现承诺」来查落点，这条会被漏掉
    # —— 而已兑现的承诺带不带落点，与停止条件**毫无关系**。
    mixed = [
        Commitment(id="c-done", kind="theme", statement="已兑现", must_hold_at=["s-1"], satisfied=True),
        Commitment(id="c-todo", kind="ending", statement="待兑现", must_hold_at=[]),
    ]
    r = preflight(_ir(commitments=mixed))
    t.ok(not r.ok, "已兑现的有落点 + 未兑现的没落点 → 仍然阻断")
    t.eq(r.blockers[0].evidence.get("reason"), "no_anchor", "落点只认未兑现承诺的那一条")

    # -- 角色没有 need：警告，不阻断 --
    needless = [
        Character(
            id="ch-1", name="林砚", want="清掉名单", need="",
            flaw="从不求助", arc_from="独行", arc_to="交出刀",
        )
    ]
    r = preflight(_ir(characters=needless))
    t.ok(r.ok, "缺 need 只警告，不阻断（分不清「没设计」与「设计得不好」）")
    t.eq(_checks(r.warnings), {"character_need"}, "缺 need → 警告 character_need")
    t.eq(len(r.blockers), 0, "缺 need → 零阻断项")


# ---------------------------------------------------------------------------
# 3. 鲁棒性：空场景 / 空角色 / 空字符串，一律是结论不是异常
# ---------------------------------------------------------------------------


def test_robustness(t: T) -> None:
    print("\n── 4. 鲁棒性：空场景 / 空角色不崩 ──")
    r = preflight(_ir(scenes=[]))
    t.ok(r.ok, "空场景列表 + 好计划 → 放行（本模块按设计不读 scenes）")
    t.eq(r.checks_run, len(CHECK_IDS), "空场景时仍跑完全部检查")

    r = preflight(_ir(characters=[]))
    t.ok(r.ok, "空角色表不崩（只是警告）")
    t.eq(_checks(r.warnings), {"character_need"}, "空角色表 → character_need 警告")

    # 全空 + 空场景：每条缺失都是结论，不是异常
    bare = _ir(premise="", ending_anchor="", controlling_idea="", commitments=[], characters=[], scenes=[])
    r = preflight(bare)
    t.ok(not r.ok, "全空计划不放行")
    t.eq(len(r.blockers), 4, "全空计划恰好四条阻断项")

    # 只有空白字符，与空串等价
    ws = _ir(premise="   ", ending_anchor="\n\t", controlling_idea="  ")
    t.eq(len(preflight(ws).blockers), 3, "纯空白字符视同缺失（3 条：锚点/前提/控制理念）")

    # 不可变：preflight 不许改 IR 一个字段
    before = _ir()
    snapshot = before.fingerprint()
    preflight(before)
    assert_ready(before)
    t.eq(before.fingerprint(), snapshot, "preflight / assert_ready 不修改 IR")


# ---------------------------------------------------------------------------
# 4. assert_ready
# ---------------------------------------------------------------------------


def test_assert_ready(t: T) -> None:
    print("\n── 5. assert_ready：阻断就抛，且消息里带修改建议 ──")
    bad = _ir(premise="关于信任", ending_anchor="释然", controlling_idea="", commitments=[])
    try:
        assert_ready(bad)
        t.ok(False, "有阻断项时应当抛 PreflightError", "它没抛")
    except PreflightError as exc:
        msg = str(exc)
        t.ok(True, "有阻断项时抛 PreflightError")
        t.ok("premise" in msg or "前提" in msg, "异常消息里能看到前提那条")
        t.ok("→" in msg, "异常消息里带 suggestion（Finding.render 的 → 行）")
        t.ok(
            all(check in msg for check in ("结局锚点", "控制理念")),
            "异常消息覆盖全部阻断项",
            msg,
        )

    # 只有警告项时不抛
    try:
        assert_ready(_ir(characters=[]))
        t.ok(True, "只有警告项时不抛（允许开跑）")
    except PreflightError as exc:
        t.ok(False, "只有警告项时不抛", str(exc))


# ---------------------------------------------------------------------------
# 5. 每条阻断项都必须带 suggestion
# ---------------------------------------------------------------------------


def test_every_finding_has_suggestion(t: T) -> None:
    print("\n── 6. 每条结论都带 actionable 建议 ──")
    plans = [
        _ir(premise="", ending_anchor="", controlling_idea="", commitments=[], characters=[]),
        _ir(premise="关于信任", ending_anchor="释然"),
        _ir(commitments=[Commitment(id="c1", kind="theme", statement="x", must_hold_at=[])]),
        _ir(
            commitments=[
                Commitment(id="c1", kind="theme", statement="x", must_hold_at=["s1"], satisfied=True)
            ]
        ),
    ]
    total = 0
    for i, plan in enumerate(plans):
        r = preflight(plan)
        for f in r.blockers + r.warnings:
            total += 1
            t.ok(
                bool(f.suggestion and f.suggestion.strip()),
                f"计划{i} 的 {f.evidence.get('check')} 带 suggestion",
            )
            t.eq(f.code, "preflight", f"计划{i} 的 finding code == 'preflight'")
            t.ok(f.evidence.get("check") in CHECK_IDS, f"check id 在 CHECK_IDS 里")
    t.ok(total >= 8, f"共检查了 {total} 条结论（覆盖所有检查项）")

    # 严重度语义：阻断项全 ERROR，警告项全 WARN
    r = preflight(plans[0])
    t.ok(all(f.severity is Severity.ERROR for f in r.blockers), "阻断项全是 ERROR")
    t.ok(all(f.severity is Severity.WARN for f in r.warnings), "警告项全是 WARN")


# ---------------------------------------------------------------------------
# 6. 与成品校验器的分界（本模块不读 scenes 的可机检形式）
# ---------------------------------------------------------------------------


def test_scene_independence(t: T) -> None:
    print("\n── 7. 不读场景：计划门禁与成品校验器的分界 ──")
    # 同一份计划，场景从 0 场变成「有 3 场」，结论必须完全一致 ——
    # 本模块判的是计划，不是成品。
    from loom.ir.enums import Focalization, SceneOutcome
    from loom.ir.models import SceneNode, TimePoint

    scenes = [
        SceneNode(
            id=f"s-{i}",
            title=f"第{i}场",
            focalizer="ch-1",
            narrator="narrator",
            focalization=Focalization.INTERNAL,
            fabula_time=TimePoint(day=i),
            sjuzhet_index=i,
            value="信任",
            value_charge_start="-",
            value_charge_end="+",
            goal="g",
            conflict="c",
            turning_point="t",
            outcome=SceneOutcome.YES_BUT,
        )
        for i in range(3)
    ]
    with_scenes = preflight(_ir(scenes=scenes))
    without = preflight(_ir(scenes=[]))
    t.eq(with_scenes.ok, without.ok, "有没有场景不改变结论")
    t.eq(len(with_scenes.blockers), len(without.blockers), "有没有场景不改变阻断项数量")

    # 承诺指向**尚不存在**的场景：计划阶段这是正常的（场景还没生成），
    # 故 preflight 不报 —— 那是 commitment_satisfied（成品校验器）的活。
    r = preflight(
        _ir(commitments=[Commitment(id="c1", kind="ending", statement="x", must_hold_at=["s-99"])])
    )
    t.ok(r.ok, "must_hold_at 指向不存在的场景时不报（生成之前这是常态）")

    # 变异体：把同一份 IR 深拷贝后改坏，结论必须变 —— 防「永远返回 ok=True」
    twin = deepcopy(_ir())
    twin.commitment.ending_anchor = "释然"
    t.ok(preflight(_ir()).ok and not preflight(twin).ok, "改坏锚点后 ok 翻转（不是永远放行）")


# ---------------------------------------------------------------------------


def main() -> int:
    t = T()
    print("═" * 64)
    print("  preflight —— 自主运行前的计划门禁")
    print("═" * 64)
    test_good_plan_silent(t)
    test_empty_plan(t)
    test_each_check_fires_alone(t)
    test_robustness(t)
    test_assert_ready(t)
    test_every_finding_has_suggestion(t)
    test_scene_independence(t)

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
