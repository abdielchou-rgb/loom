"""认知负荷窗口累加 —— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**。
期望值从模块 docstring 里声明的先验常量推导，不是从实现里抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_cognitive.py

零依赖（不用 pytest），与 `tests/test_csn.py` 同风格。

── 为什么这个文件的核心是「窗口」而不是「单场」 ────────────

单场负荷的测试**证明不了本模块的价值** —— 逐场判定已经由
`loom/audience/simulator.hazard` 在做。本模块唯一值得存在的能力是
**跨场累加**，所以第 4 组是核心：

    sc0  负荷 0.0
    sc1  负荷 5.0   <- 单看没事
    sc2  负荷 5.0   <- 单看没事
    sc3  负荷 5.0   <- 单看没事
    window=3 的累计：0 / 5 / 10 / **15**  -> 只有第 4 场越过 12

三场各自合格，挤在一起才超线。这才是「窗口累加」与「逐场判定」的区别。
只测单场负荷的测试套件，把 window 参数改成 1 也照样全绿 —— 那就没测到功能。

第 5 组证明**上下文真的改变结论**：同一个场景对象，换一个前置场景，
负荷从 15.0 掉到 1.5（阈值 12）。两处用的 IR 字段完全相同，
差别只在「前面发生过什么」。

── 关于断言风格 ────────────────────────────────────────

全部断言**精确数值**（15.0 / 1.5 / 12.5），不用 `> 0` 这类真值断言。
理由：本模块的产出就是一个数，真值断言在权重被改错时仍然会通过 ——
把 ×0.5 写成 ×0.4，`ok(total > 0)` 抓不到，`eq(total, 1.5)` 能抓到。

── 期望值的来源 ────────────────────────────────────────

输入维度（视角 / 时间 / 空间 / 新角色 / 闪回）取自事件索引模型
（Zwaan, Langston & Graesser 1995；Zwaan & Radvansky 1998）与
Magliano, Miller & Zwaan 2001（Applied Cognitive Psychology 15(5): 533-545）。
**但具体数值是先验，不是从这些文献读出来的系数** —— 见模块 docstring。
下面的用例测的是「结构对不对」（累加、上下文敏感、阈值边界、折扣规则），
不是「权重科不科学」。
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
# 构造工具 —— 只填本模块真正读取的字段
# ---------------------------------------------------------------------------


def _s(
    sid: str,
    *,
    i: int,
    focalizer: str = "a",
    location: str | None = "L1",
    day: int = 0,
    label: str | None = None,
    entities: tuple[str, ...] = (),
    flashback: bool = False,
    freq=None,
):
    from loom.ir.enums import Frequency, SceneOutcome
    from loom.ir.models import SceneNode, TimePoint

    return SceneNode(
        id=sid,
        title=sid,
        focalizer=focalizer,
        narrator="narrator",
        fabula_time=TimePoint(day=day, label=label, is_flashback=flashback),
        sjuzhet_index=i,
        frequency=freq or Frequency.SINGULATIVE,
        value="信任",
        value_charge_start="+",
        value_charge_end="-",
        goal="谁想要什么",
        conflict="谁阻碍",
        turning_point="转折",
        outcome=SceneOutcome.YES,
        entities=list(entities),
        location=location,
    )


def _ir(scenes):
    from loom.ir.enums import ArcShape
    from loom.ir.models import CommitmentLayer, NarrativeIR

    return NarrativeIR(
        title="测试",
        commitment=CommitmentLayer(
            premise="p",
            controlling_idea="ci",
            logline="l",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="e",
        ),
        scenes=list(scenes),
    )


# ---------------------------------------------------------------------------
# 1. 单场负荷的可解释分解
# ---------------------------------------------------------------------------


def test_scene_load(t: T) -> None:
    from loom.audience.cognitive import CognitivePriors, scene_load

    t.group("1. 单场负荷分解（精确数值）")

    # 视角切换 4 + 时间跳变（年，2×3）6 + 空间变化 2 + 新角色 3 = 15.0
    prev = _s("prev", i=0, focalizer="a", location="L1", day=0, entities=("x",))
    target = _s("t", i=1, focalizer="b", location="L2", day=400, entities=("c",))
    bd = scene_load(target, {"x"}, prev)
    t.eq(bd.total, 15.0, "全要素场景总负荷")
    t.eq(
        bd.parts,
        {
            "pov_switch": 4.0,
            "time_jump": 6.0,
            "location_change": 2.0,
            "new_character": 3.0,
        },
        "parts 逐项分解（每个贡献都留痕）",
    )

    # 首场无前置：视角/时间/空间三类「跳变」都无从谈起，只剩入场角色
    bd = scene_load(target, set(), None)
    t.eq(bd.total, 3.0, "无前置场景 -> 只有新角色成本")
    t.eq(bd.parts, {"new_character": 3.0}, "无前置场景的 parts 只有一项")

    # 一切连续：零负荷，parts 为空（非零项才写进去）
    same = _s("same", i=1, focalizer="a", location="L1", day=0)
    bd = scene_load(same, set(), prev)
    t.eq(bd.total, 0.0, "完全连续 -> 零负荷")
    t.eq(bd.parts, {}, "零负荷时 parts 为空字典")

    # 地点未标注 = 未知，不臆测变化（保守，避免误报）
    bd = scene_load(_s("nl", i=1, location=None), set(), prev)
    t.eq(bd.parts, {}, "地点未标注 -> 不判定空间变化")

    # 时间跳变按量级缩放
    bd = scene_load(_s("m", i=1, day=30), set(), prev)
    t.eq(bd.parts, {"time_jump": 6.0}, "跳 30 天 -> 月量级 2×3=6")

    # 上限把「年」和「月」压成同一个乘数 —— 这本身就是先验未校准的证据
    bd = scene_load(_s("y", i=1, day=365), set(), prev)
    t.eq(bd.parts, {"time_jump": 6.0}, "跳 365 天 -> 年被 cap=3 压到 6（与月同价）")

    # 先验可整块替换 —— 这才是「暴露成参数」的意义
    wide = CognitivePriors(time_magnitude_cap=10.0)
    bd = scene_load(_s("y2", i=1, day=365), set(), prev, priors=wide)
    t.eq(bd.parts, {"time_jump": 20.0}, "cap=10 时年跳变 2×10=20（可重校准）")
    bd = scene_load(_s("m2", i=1, day=30), set(), prev, priors=wide)
    t.eq(bd.parts, {"time_jump": 6.0}, "cap=10 时月跳变仍为 2×3=6")


# ---------------------------------------------------------------------------
# 2. 角色成本：首次出场 vs 回归
# ---------------------------------------------------------------------------


def test_character_cost(t: T) -> None:
    from loom.audience.cognitive import scene_load

    t.group("2. 角色成本（×0.5 回归折扣）")

    prev = _s("prev", i=0, location="L1", entities=("x",))

    bd = scene_load(_s("t", i=1, location="L1", entities=("c",)), {"x"}, prev)
    t.eq(bd.parts, {"new_character": 3.0}, "首次出场 -> 全额 3.0")

    bd = scene_load(_s("t", i=1, location="L1", entities=("c",)), {"x", "c"}, prev)
    t.eq(bd.parts, {"new_character": 1.5}, "见过但不在上一场 -> 回归 3.0×0.5=1.5")

    # 连续在场 = 不需要重新索引，零成本（否则每个场景都会恒有角色成本）
    prev2 = _s("prev", i=0, location="L1", entities=("c",))
    bd = scene_load(_s("t", i=1, location="L1", entities=("c",)), {"c"}, prev2)
    t.eq(bd.parts, {}, "连续在场的角色 -> 不产生入场成本")

    # 一场多角色：新 + 回归混算
    bd = scene_load(
        _s("t", i=1, location="L1", entities=("c1", "c2")), {"c1"}, prev
    )
    t.eq(bd.total, 4.5, "一回归 + 一新 = 1.5 + 3.0")
    t.eq(bd.parts, {"new_character": 4.5}, "混合角色成本合并进同一项")


# ---------------------------------------------------------------------------
# 3. 闪回类信号
# ---------------------------------------------------------------------------


def test_flashback_signals(t: T) -> None:
    from loom.ir.enums import Frequency
    from loom.audience.cognitive import scene_load

    t.group("3. 闪回类信号（is_flashback / frequency）")

    prev = _s("prev", i=0, location="L1", day=0)

    bd = scene_load(_s("t", i=1, location="L1", flashback=True), set(), prev)
    t.eq(bd.parts, {"flashback": 3.0}, "is_flashback -> 3.0")

    bd = scene_load(
        _s("t", i=1, location="L1", freq=Frequency.REPETITIVE), set(), prev
    )
    t.eq(bd.parts, {"flashback": 3.0}, "REPETITIVE（一事多讲）-> 3.0")

    bd = scene_load(
        _s("t", i=1, location="L1", freq=Frequency.ITERATIVE), set(), prev
    )
    t.eq(bd.parts, {"flashback": 3.0}, "ITERATIVE（多事一讲）-> 3.0")

    bd = scene_load(_s("t", i=1, location="L1"), set(), prev)
    t.eq(bd.parts, {}, "SINGULATIVE 且非闪回 -> 不产生该成本")


# ---------------------------------------------------------------------------
# 4. 【核心】窗口累加 —— 三场各自合格，挤在一起超线
# ---------------------------------------------------------------------------


def _accumulation_ir():
    """sc0 0.0 / sc1 5.0 / sc2 5.0 / sc3 5.0 —— 每场都远低于阈值 12。"""
    return _ir(
        [
            _s("sc0", i=0, location="L0"),
            _s("sc1", i=1, location="L1", entities=("c1",)),
            _s("sc2", i=2, location="L2", entities=("c2",)),
            _s("sc3", i=3, location="L3", entities=("c3",)),
        ]
    )


def test_window_accumulation(t: T) -> None:
    from loom.audience.cognitive import scan_ir, scene_load, windowed_loads

    t.group("4. 【核心】窗口累加（单场合格，累计超线）")

    ir = _accumulation_ir()

    # 先证明每一场**单独**都远低于阈值 —— 这是本组的立足点
    prev = None
    seen: set[str] = set()
    singles = []
    for s in ir.ordered_scenes():
        bd = scene_load(s, seen, prev)
        singles.append(bd.total)
        seen.update(s.entities)
        prev = s
    t.eq(singles, [0.0, 5.0, 5.0, 5.0], "逐场负荷（全部 < 12，单看都没问题）")
    t.ok(max(singles) < 12.0, "任何单场都未越过阈值")

    # 窗口累加：只有第 4 场（窗口覆盖 sc1..sc3）越线
    loads = windowed_loads(ir, window=3)
    t.eq(
        loads,
        [("sc0", 0.0), ("sc1", 5.0), ("sc2", 10.0), ("sc3", 15.0)],
        "window=3 累计：0 / 5 / 10 / 15 —— 三场温和场景叠加后超线",
    )

    # 门禁策略：默认 INFO（负荷画像），仅超阈值升 WARN
    findings = scan_ir(ir, window=3, threshold=12.0)
    t.eq(len(findings), 4, "每场一条 Finding（负荷画像）")
    t.eq(
        [f.severity.value for f in findings],
        ["info", "info", "info", "warn"],
        "只有累计超阈值的那一场是 WARN，其余 INFO",
    )
    t.eq(findings[-1].scene_id, "sc3", "WARN 落在造成累计越线的那一场")
    t.eq(findings[-1].code, "cognitive_load_window", "Finding code")
    t.eq(findings[-1].evidence["total"], 15.0, "evidence 带上累计值，便于解释")
    t.eq(
        findings[-1].evidence["window_parts"],
        {"location_change": 6.0, "new_character": 9.0},
        "evidence 带上窗口内各因子合计（可解释到因子级）",
    )


def test_window_sizes(t: T) -> None:
    from loom.audience.cognitive import windowed_loads

    t.group("5. 窗口宽度语义")

    ir = _accumulation_ir()
    t.eq(
        [v for _, v in windowed_loads(ir, window=1)],
        [0.0, 5.0, 5.0, 5.0],
        "window=1 退化为逐场负荷",
    )
    t.eq(
        [v for _, v in windowed_loads(ir, window=2)],
        [0.0, 5.0, 10.0, 10.0],
        "window=2 覆盖当前场 + 前一场",
    )
    t.eq(
        [v for _, v in windowed_loads(ir, window=10)],
        [0.0, 5.0, 10.0, 15.0],
        "窗口大于篇幅 -> 等价于全篇累计",
    )
    t.eq(windowed_loads(_ir([])), [], "空 IR -> 空列表")


# ---------------------------------------------------------------------------
# 6. 上下文改变结论
# ---------------------------------------------------------------------------


def test_context_changes_verdict(t: T) -> None:
    from loom.audience.cognitive import scene_load, windowed_loads

    t.group("6. 上下文改变结论（同一个场景，两种判定）")

    target = _s("t", i=1, focalizer="b", location="L2", day=400, entities=("c",))

    heavy_prev = _s("p1", i=0, focalizer="a", location="L1", day=0, entities=("x",))
    mild_prev = _s("p2", i=0, focalizer="b", location="L2", day=400, entities=("x",))

    heavy = scene_load(target, {"x"}, heavy_prev)
    mild = scene_load(target, {"x", "c"}, mild_prev)

    t.eq(heavy.total, 15.0, "陌生上下文：视角/时间/空间/角色四项齐发 -> 15.0")
    t.eq(mild.total, 1.5, "已就位上下文：只付回归角色的折扣价 -> 1.5")
    t.ok(heavy.total > 12.0 >= mild.total, "同一个场景：一边越线，一边远低于阈值")

    t.group("6b. 折扣在窗口里同样生效")

    # 同一个目标场景、同样的窗口宽度，唯一差别是「角色此前是否已登场」
    prepared = _ir(
        [
            _s("sc0", i=0, location="L1", entities=("c",)),
            _s("sc1", i=1, location="L1"),
            _s("sc2", i=2, location="L1", entities=("c",)),
        ]
    )
    cold = _ir(
        [
            _s("sc0", i=0, location="L1"),
            _s("sc1", i=1, location="L1"),
            _s("sc2", i=2, location="L1", entities=("c",)),
        ]
    )
    t.eq(
        windowed_loads(prepared, window=2)[-1],
        ("sc2", 1.5),
        "角色已登场 -> 窗口累计 1.5",
    )
    t.eq(
        windowed_loads(cold, window=2)[-1],
        ("sc2", 3.0),
        "角色未曾登场 -> 同一场景窗口累计 3.0",
    )


# ---------------------------------------------------------------------------
# 7. 阈值边界
# ---------------------------------------------------------------------------


def test_threshold_boundary(t: T) -> None:
    from loom.audience.cognitive import scan_ir

    t.group("7. 阈值边界（12.0 恰好不报）")

    # 11.5 = 视角 4 + 年跳变 6 + 回归角色 1.5
    below = _ir(
        [
            _s("sc0", i=0, location="L1", entities=("c",)),
            _s("sc1", i=1, location="L1"),
            _s("sc2", i=2, focalizer="b", location="L1", day=400, entities=("c",)),
        ]
    )
    f = scan_ir(below, window=1, threshold=12.0)
    t.eq(f[-1].evidence["total"], 11.5, "略低于阈值 -> 11.5")
    t.eq(f[-1].severity.value, "info", "略低于阈值 -> INFO")

    # 12.0 = 视角 4 + 年跳变 6 + 空间 2，恰好等于阈值
    at = _ir(
        [
            _s("sc0", i=0, location="L1"),
            _s("sc1", i=1, focalizer="b", location="L2", day=400),
        ]
    )
    f = scan_ir(at, window=1, threshold=12.0)
    t.eq(f[-1].evidence["total"], 12.0, "恰好等于阈值 -> 12.0")
    t.eq(f[-1].severity.value, "info", "恰好等于阈值 -> 仍为 INFO（严格大于才报警）")

    # 12.5 = 视角 4 + 日跳变 2 + 空间 2 + 新角色 3 + 回归角色 1.5
    above = _ir(
        [
            _s("sc0", i=0, location="L1", entities=("c_ret",)),
            _s("sc1", i=1, location="L1"),
            _s(
                "sc2",
                i=2,
                focalizer="b",
                location="L2",
                day=5,
                entities=("c_ret", "c_new"),
            ),
        ]
    )
    f = scan_ir(above, window=1, threshold=12.0)
    t.eq(f[-1].evidence["total"], 12.5, "略高于阈值 -> 12.5")
    t.eq(f[-1].severity.value, "warn", "略高于阈值 -> WARN")
    t.ok(f[-1].suggestion, "WARN 必须给出可执行建议")

    # 阈值可调
    f = scan_ir(above, window=1, threshold=13.0)
    t.eq(f[-1].severity.value, "info", "阈值调高到 13.0 -> 同一条不再报警")


# ---------------------------------------------------------------------------

def main() -> int:
    print("═" * 64)
    print("  认知负荷窗口累加 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_scene_load(t)
        test_character_cost(t)
        test_flashback_signals(t)
        test_window_accumulation(t)
        test_window_sizes(t)
        test_context_changes_verdict(t)
        test_threshold_boundary(t)
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
