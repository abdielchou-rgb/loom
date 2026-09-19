"""张力播种（TensionSeeder）—— 测试先行。

跑法：
    .venv/Scripts/python.exe tests/test_tension.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `tests/test_tom.py` 同风格。

── 这个模块为什么需要单独的测试 ────────────────────────

`tests/test_tom.py` 测的是**派生函数**（`derive_tension_points`）：
给它信念状态与真值层，它能不能算出张力。那是纯函数，好测。

本文件测的是**播种器**（`TensionSeeder`）：它得先**造出**信念状态与真值层。
这里有一个特别容易走偏的地方 ——

    **播种器不该制造它自己要抓的缺陷。**

如果 `TensionSeeder` 播下的信念与它自己写进真值层的值不一致，
`belief_consistency` 就会在干净基线上报警。那一刻看起来很「成功」
（张力更多了！），实际上是自欺：基线不再干净，而 `verify.py` 的
「零误报」断言会被一个**由播种器自己造成的**误报打红。
第 2 组专门断言这条性质：**播种出来的信念与真值层是自洽的。**

── 第 4 组是能力边界，不是遗漏 ────────────────────────

`known_secrets` 与递归信念**刻意不播种**。秘密需要一份作者声明的
「谁知道什么」台账；从 `wound` 反推等于替作者发明一个他没声明过的秘密，
而 `secret_reveal_ordering` 会因此报出一个作者无法理解的 WARN。
第 4 组把这个边界钉成断言 —— 否则下一个人会「顺手补上」它。

── 变异测试 ───────────────────────────────────────────

第 8 组是变异测试：把 `lie` 清空，断言戏剧反讽随之消失。
只断言「有反讽」是不够的 —— 一个 `return 固定三条` 的实现也能通过。
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
# 构造工具
# ---------------------------------------------------------------------------

_IDEA = "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字"

#: 严重度序（与 scripts/verify.py 同口径）。避免在断言里到处写字符串比较。
from keel.ir.enums import Severity  # noqa: E402

SEV = {Severity.INFO: 0, Severity.WARN: 1, Severity.ERROR: 2}


def _pipeline_ir(scene_count: int = 6, words: int = 200):
    """跑一遍离线流水线，拿一份**未经 fixture 收尾**的 IR。

    刻意不经过 `tests.fixtures.build_clean_ir`：那份 IR 被收尾过
    （溯源改人工、补关系、清提案），用它测播种器会掩盖播种行为本身。
    本文件要看的正是「流水线自己产出了什么」。
    """
    from keel.ir.enums import ArcShape, Medium
    from keel.llm import MockGenerator
    from keel.pipeline import KeelPipeline

    return KeelPipeline(MockGenerator()).run(
        _IDEA,
        medium=Medium.NOVEL,
        arc_shape=ArcShape.MAN_IN_A_HOLE,
        scene_count=scene_count,
        words_per_scene=words,
        max_rounds=0,
    ).ir


def _bare_ir(**kw):
    """最小可用的 IR，用来测播种器的边界（缺字段时不该炸）。"""
    from keel.ir.enums import ArcShape
    from keel.ir.models import Character, CharacterLayer, CommitmentLayer, NarrativeIR

    chars = CharacterLayer()
    for cid in kw.pop("characters", []):
        # Character 的这几个字段是必填的（schema 是硬契约）——
        # 这里给空串而不是省略，因为本测试要测的是**缺 lie** 的行为，
        # 不是「能不能构造出一个半成品 Character」。
        chars.add(
            Character(
                id=cid, name=cid, want="", need="", flaw="", arc_from="", arc_to=""
            )
        )
    return NarrativeIR(
        title="t",
        commitment=CommitmentLayer(
            premise="p",
            controlling_idea="c",
            logline="l",
            ending_anchor="e",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
        ),
        characters=chars,
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. 真值层从 lie 反推
# ---------------------------------------------------------------------------


def test_seed_truth_from_lie(t: T) -> None:
    from keel.pipeline.engines import TensionSeeder

    t.group("1. 真值层从 lie 反推")

    ir = _pipeline_ir()
    lies = {c.lie for c in ir.characters.characters.values() if c.lie}
    t.ok(bool(lies), "流水线产出了 lie（否则后面全部无从测起）")

    TensionSeeder().run(ir)
    for lie in lies:
        t.eq(ir.objective_truth.get(lie), False, f"lie 被记为「故事世界不成立」：{lie[:16]}…")

    # 已存在的真值**不被覆盖** —— 作者显式给的值优先。
    author = "作者显式给的一条真值"
    ir2 = _pipeline_ir()
    first_lie = next(c.lie for c in ir2.characters.characters.values() if c.lie)
    ir2.objective_truth[first_lie] = "作者说这是真的"
    TensionSeeder().run(ir2)
    t.eq(
        ir2.objective_truth[first_lie],
        "作者说这是真的",
        "作者显式给的真值不被播种器覆盖",
    )

    # 没有 lie 的 IR：安静地什么都不做，不抛异常。
    ir3 = _bare_ir(characters=["a"])
    t.eq(TensionSeeder().run(ir3), [], "无 lie / 无信念时返回空列表（不抛异常）")


# ---------------------------------------------------------------------------
# 2. 播种出来的信念与真值层自洽（播种器不制造自己的反例）
# ---------------------------------------------------------------------------


def test_seeded_beliefs_are_self_consistent(t: T) -> None:
    from keel.ir.enums import Severity
    from keel.pipeline.engines import TensionSeeder
    from keel.validators import run_all

    t.group("2. 播种出来的信念与真值层自洽")

    ir = _pipeline_ir()
    # 播种**之前**先体检一次。必须这样比，不能直接断言「0 ERROR + 0 WARN」：
    # 流水线产出的 IR 本来就带一条合规 WARN（正文全是 AI 生成，占比 100%），
    # 那条与播种无关。直接断言 0 WARN 会把「播种干净」和「基线本来干净」
    # 混为一谈，而这两件事要分开看。
    before = run_all(ir)
    before_sev = {f.code: f.severity for f in before.findings}

    TensionSeeder().run(ir)

    for ch in ir.characters.characters.values():
        bs = ch.belief_state
        if bs is None or not ch.lie:
            continue
        belief = bs.world_beliefs[ch.lie]
        t.eq(belief.value, True, f"{ch.id} 相信自己的 lie")
        t.eq(
            belief.is_erroneous,
            True,
            f"{ch.id} 的 lie 信念被自动标为错误信念（来源=误解）",
        )
        t.eq(
            ir.objective_truth[ch.lie],
            False,
            f"{ch.id} 的 lie 在真值层为假 —— 与 is_erroneous 一致",
        )

    after = run_all(ir)

    # 核心断言：播种**没有新增任何** ERROR/WARN。
    # 新增了就说明播种器在制造自己的反例（见文件 docstring）。
    new_severe = [
        f"{f.code}({f.severity.value})"
        for f in after.findings
        if SEV[f.severity] >= SEV[Severity.WARN]
        and before_sev.get(f.code) is None
    ]
    t.eq(new_severe, [], "播种未新增任何 ERROR/WARN（播种器没制造误报）")
    t.eq(
        [f for f in after.findings if f.code == "belief_consistency"],
        [],
        "播种后 belief_consistency 零发现",
    )
    t.eq(after.crashes, {}, "播种不导致任何校验器崩溃")


# ---------------------------------------------------------------------------
# 3. active_goals 从显性目标与 want 取
# ---------------------------------------------------------------------------


def test_seed_active_goals(t: T) -> None:
    from keel.pipeline.engines import TensionSeeder

    t.group("3. active_goals 从显性目标与 want 取")

    ir = _pipeline_ir()
    TensionSeeder().run(ir)

    hero = ir.characters.characters["protagonist"]
    goals = hero.belief_state.active_goals
    t.ok("找到真相" in goals, "显性目标进入 active_goals")
    t.ok("查清那件事的真相" in goals, "want 也进入 active_goals")
    t.ok(
        "不再信任任何人" not in goals,
        "**非显性**目标不进 active_goals（is_conscious=False）",
    )

    # 两个角色共享「找到真相」→ 必然派生出一条目标冲突。
    points = [p for p in ir.tension_points if p.type.value == "目标冲突"]
    t.ok(bool(points), "共享目标派生出「目标冲突」张力点")
    if points:
        t.eq(sorted(points[0].involved), ["counterpart", "protagonist"], "冲突涉及双方")

    # 幂等：再跑一次不会把 active_goals 翻倍。
    before = len(hero.belief_state.active_goals)
    TensionSeeder().run(ir)
    t.eq(len(hero.belief_state.active_goals), before, "重复播种不追加 active_goals")


# ---------------------------------------------------------------------------
# 4. 能力边界：不播种秘密、不播种递归信念
# ---------------------------------------------------------------------------


def test_capability_boundary(t: T) -> None:
    from keel.pipeline.engines import TensionSeeder

    t.group("4. 能力边界：不播种秘密 / 不播种递归信念")

    ir = _pipeline_ir()
    TensionSeeder().run(ir)

    for ch in ir.characters.characters.values():
        if ch.belief_state is None:
            continue
        t.eq(
            ch.belief_state.known_secrets,
            [],
            f"{ch.id} 的 known_secrets 为空 —— 秘密必须来自作者，不能从 wound 反推",
        )
        t.eq(
            ch.belief_state.recursive_beliefs,
            {},
            f"{ch.id} 无递归信念 —— 那是创作内容，不是结构反推",
        )
        t.eq(ch.belief_state.about_others, {}, f"{ch.id} 无 about_others")

    kinds = {p.type.value for p in ir.tension_points}
    t.ok("递归错位" not in kinds, "默认产出里没有「递归错位」（能力边界，不是缺陷）")
    t.ok("秘密暴露风险" not in kinds, "默认产出里没有「秘密暴露风险」")


# ---------------------------------------------------------------------------
# 5. 端到端：张力点非空、可排序、每条都带建议
# ---------------------------------------------------------------------------


def test_end_to_end_points(t: T) -> None:
    from keel.ir.tom import TensionPoint

    t.group("5. 端到端张力点")

    ir = _pipeline_ir()
    points = ir.tension_points
    t.ok(len(points) >= 2, f"流水线产出张力点（实际 {len(points)}）")

    kinds = {p.type.value for p in points}
    t.ok("戏剧反讽" in kinds, "产出「戏剧反讽」（lie 与真值不一致）")
    t.ok("目标冲突" in kinds, "产出「目标冲突」（两人共享目标）")

    for p in points:
        t.ok(bool(p.suggestion.strip()), f"张力点带可执行建议：{p.type.value}")
        t.ok(bool(p.involved), f"张力点有涉及角色：{p.type.value}")
        t.ok(0.0 <= p.intensity <= 1.0, f"强度在 [0,1]：{p.type.value}")

    # 排序：强度降序（`derive_tension_points` 的确定性契约）
    intensities = [p.intensity for p in points]
    t.eq(intensities, sorted(intensities, reverse=True), "张力点按强度降序")
    t.eq(
        [p.type.value for p in ir.top_tensions(3)],
        [p.type.value for p in points[:3]],
        "top_tensions(n) 与排序后的前 n 条一致",
    )

    # schema 硬约束：没有建议的张力点构造不出来。
    from keel.ir.tom import TensionType

    def _no_suggestion():
        TensionPoint(
            type=TensionType.DRAMATIC_IRONY,
            involved=["a"],
            intensity=0.8,
            description="d",
            suggestion="",
        )

    try:
        _no_suggestion()
        t.ok(False, "schema 拒绝空 suggestion")
    except Exception:
        t.ok(True, "schema 拒绝空 suggestion（suggestion 是必填，靠 schema 强制）")


# ---------------------------------------------------------------------------
# 6. 幂等与上限
# ---------------------------------------------------------------------------


def test_idempotent_and_capped(t: T) -> None:
    from keel.pipeline.engines import TensionSeeder

    t.group("6. 幂等与上限")

    ir = _pipeline_ir()
    first = TensionSeeder().run(ir)
    second = TensionSeeder().run(ir)
    t.eq(len(second), len(first), "重复 run 的产出条数不变（幂等）")
    t.eq(
        [(p.type.value, p.involved) for p in second],
        [(p.type.value, p.involved) for p in first],
        "重复 run 的产出内容一致",
    )

    capped = TensionSeeder(max_points=1).run(ir)
    t.eq(len(capped), 1, "max_points 生效")
    t.eq(capped[0].intensity, first[0].intensity, "截断保留的是最强的那条")


# ---------------------------------------------------------------------------
# 7. 向前看的产出走 advisory 通道，不动健康分
# ---------------------------------------------------------------------------


def test_advisory_channel(t: T) -> None:
    from keel.validators import ADVISORY, run_all

    t.group("7. 向前看的产出走 advisory，不动健康分")

    ir = _pipeline_ir()
    report = run_all(ir)

    in_findings = [f for f in report.findings if f.code == "dramatic_irony_available"]
    in_advisory = [f for f in report.advisory if f.code == "dramatic_irony_available"]
    t.eq(in_findings, [], "dramatic_irony_available 不出现在 findings 里")
    t.ok(bool(in_advisory), "dramatic_irony_available 出现在 advisory 里")
    t.ok("dramatic_irony_available" in ADVISORY, "它在 ADVISORY 名单里")

    # 健康分口径：advisory 一条都不扣。
    base = 100 - 12 * len(report.errors) - 4 * len(report.warnings) - len(report.infos)
    t.eq(report.score(), max(0, base), "score() 不包含 advisory 条数")
    t.eq(len(report.infos), sum(1 for f in report.findings if f.severity.value == "info"),
         "infos 只数 findings，不数 advisory")


# ---------------------------------------------------------------------------
# 8. 变异测试：把 lie 清空，反讽必须随之消失
# ---------------------------------------------------------------------------


def test_mutation_lie_cleared(t: T) -> None:
    from keel.pipeline.engines import TensionSeeder

    t.group("8. 变异测试：清空 lie → 反讽消失")

    def _strip_beliefs(ir):
        """把流水线播下的信念层与真值层清干净，只留（或清掉）lie。

        为什么不能只清 `lie`：`TensionSeeder` 是在 `build_ir` 里跑的，
        拿到手的 IR 里信念层**已经播好了**。只把 lie 清空而留着信念，
        反讽当然还在 —— 那样测的是「信念层在不在」，不是「lie 在不在」。
        """
        for ch in ir.characters.characters.values():
            ch.belief_state = None
        ir.objective_truth = {}
        ir.tension_points = []

    # 对照组：保留 lie，清掉信念层 → 播种应当把反讽造回来。
    control = _pipeline_ir()
    _strip_beliefs(control)
    control_points = TensionSeeder().run(control)
    t.ok(
        any(p.type.value == "戏剧反讽" for p in control_points),
        "对照：保留 lie 时播种产出戏剧反讽",
    )

    # 变异组：连 lie 一起清掉 → 反讽必须消失。
    mutated = _pipeline_ir()
    _strip_beliefs(mutated)
    for ch in mutated.characters.characters.values():
        ch.lie = ""
    points = TensionSeeder().run(mutated)
    t.eq(
        [p for p in points if p.type.value == "戏剧反讽"],
        [],
        "清空 lie 后不再产出戏剧反讽（证明断言测的是播种，不是常数）",
    )

    # 目标冲突**不受** lie 影响 —— 两个来源必须可分离，否则说明有串扰。
    t.ok(
        any(p.type.value == "目标冲突" for p in points),
        "清空 lie 不影响「目标冲突」（两个来源相互独立）",
    )


# ---------------------------------------------------------------------------


def main() -> int:
    t = T()
    test_seed_truth_from_lie(t)
    test_seeded_beliefs_are_self_consistent(t)
    test_seed_active_goals(t)
    test_capability_boundary(t)
    test_end_to_end_points(t)
    test_idempotent_and_capped(t)
    test_advisory_channel(t)
    test_mutation_lie_cleared(t)

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
