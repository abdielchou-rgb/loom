"""工艺装置分类学与饱和检测（`loom/ir/devices.py`）—— 测试先行。

跑法：
    .venv/Scripts/python.exe tests/test_devices.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `tests/test_tom.py` 同风格。

── 第 4 组是回归测试，它记录了一个真实的静默缺陷 ────────

`pattern_saturation` 原先写的是 `st.storylet_ids`（在 **Storylet** 上找
`storylet_ids`），而这个字段其实住在 **SceneNode** 上。这个错误的特征极其
隐蔽：

    在没有 storylet 的 IR 上，列表推导的生成器表达式体**根本不求值**，
    所以永远不会报错；在有 storylet 的 IR 上必崩 AttributeError。

于是「干净基线全绿」与「这个分支从来没跑过」同时成立 —— 而崩溃当时被
`run_all` 包成了一条普通 INFO 发现，混在报告里没人看得出来。
它漂了很久，最后是靠给 `verify.py` 加「校验器不许崩溃」断言才抓到的。

第 4 组现在把这条分支**钉死**：构造一个带 storylet 且 storylet 显式声明了
`patterns` 的 IR，断言 (a) 不崩、(b) 显式声明优先于关键词反推。
少了这一组，同样的错误可以再犯一次而没人发现。
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
# 1. 分类学完整性
# ---------------------------------------------------------------------------


def test_taxonomy(t: T) -> None:
    from loom.ir.devices import (
        ALL_PATTERNS,
        CONFLICT_TYPES,
        EMOTIONAL_ARCS,
        PLEASURE_TYPES,
    )

    t.group("1. 分类学完整性")

    t.ok(len(PLEASURE_TYPES) > 0, "PLEASURE_TYPES 非空")
    t.ok(len(CONFLICT_TYPES) > 0, "CONFLICT_TYPES 非空")
    t.ok(len(EMOTIONAL_ARCS) > 0, "EMOTIONAL_ARCS 非空")
    t.eq(
        ALL_PATTERNS,
        PLEASURE_TYPES + CONFLICT_TYPES + EMOTIONAL_ARCS,
        "ALL_PATTERNS 是三个子类的有序拼接（不是另抄一份）",
    )
    t.eq(len(ALL_PATTERNS), len(set(ALL_PATTERNS)), "ALL_PATTERNS 无重复项")
    t.eq(
        len(set(PLEASURE_TYPES) & set(CONFLICT_TYPES)),
        0,
        "爽感与冲突两类不交叉",
    )
    t.ok(
        all(isinstance(p, str) and p.strip() for p in ALL_PATTERNS),
        "所有装置名都是非空字符串",
    )

    # 装置名必须能出现在中文正文里 —— 带 ASCII 字母或空格的装置名
    # 在子串匹配下几乎不可能命中（这是一条设计约束，不是洁癖）。
    weird = [p for p in ALL_PATTERNS if any(ch.isascii() and ch.isalpha() for ch in p)]
    t.eq(weird, [], "装置名不含 ASCII 字母（子串匹配要求它们是中文词）")


# ---------------------------------------------------------------------------
# 2. infer_patterns
# ---------------------------------------------------------------------------


def test_infer_patterns(t: T) -> None:
    from loom.ir.devices import ALL_PATTERNS, infer_patterns

    t.group("2. infer_patterns（线性叙事的兜底通道）")

    t.eq(infer_patterns(""), [], "空文本返回空列表（不抛异常）")
    t.eq(infer_patterns("   "), [], "空白文本返回空列表")
    t.eq(
        infer_patterns("他数了数包袱里的东西，比昨天少了一件。"),
        [],
        "无关文本返回空列表 —— **保守**是刻意的：认不出就说认不出",
    )

    # 命中：用分类学里真实存在的装置名构造文本。
    sample = ALL_PATTERNS[0]
    got = infer_patterns(f"这一场是他{sample}的场面")
    t.eq(got, [sample], f"命中装置「{sample}」")

    # 多个命中时，顺序跟随 ALL_PATTERNS（不是文本出现顺序）——
    # 确定性输出是回归测试能断言的前提。
    if len(ALL_PATTERNS) >= 2:
        a, b = ALL_PATTERNS[0], ALL_PATTERNS[1]
        got2 = infer_patterns(f"{b}…然后{a}")
        t.eq(got2, [a, b], "多个命中按 ALL_PATTERNS 顺序返回（确定性）")

    # 重复出现只报一次。
    t.eq(infer_patterns(f"{sample}{sample}{sample}"), [sample], "同一装置重复只报一次")

    # 全量：把整个分类学拼进文本，应当全部命中且顺序一致。
    t.eq(
        infer_patterns("、".join(ALL_PATTERNS)),
        list(ALL_PATTERNS),
        "全量命中且顺序与 ALL_PATTERNS 一致",
    )


# ---------------------------------------------------------------------------
# 3. check_saturation
# ---------------------------------------------------------------------------


def test_check_saturation(t: T) -> None:
    from loom.ir.devices import check_saturation

    t.group("3. check_saturation（窗口化饱和检测）")

    t.eq(check_saturation([]), [], "空序列返回空")
    t.eq(
        check_saturation(["打脸"], window=5),
        [("打脸", 1.0)],
        "单元素序列：窗口按实际长度归一 → 1.0（**原语只负责算**）",
    )
    t.eq(check_saturation(["a", "b", "c"], window=0), [], "window<=0 直接返回空（不做除零）")

    # 判据是 `>= threshold`。
    seq = ["打脸", "打脸", "觉醒", "打脸", "打脸"]  # 4/5 = 0.8
    got = dict(check_saturation(seq, window=5, threshold=0.6))
    t.eq(round(got.get("打脸", 0), 4), 0.8, "4/5 → 0.8")
    t.ok("觉醒" not in got, "1/5 → 0.2，低于阈值，不报")

    # 窗口只取**最近** window 项。
    seq2 = ["打脸"] * 3 + ["觉醒", "觉醒", "觉醒", "觉醒", "觉醒"]
    got2 = dict(check_saturation(seq2, window=5, threshold=0.6))
    t.ok("打脸" not in got2, "窗口外的重复不算 —— 只看最近 window 项")
    t.eq(round(got2.get("觉醒", 0), 4), 1.0, "窗口内 5/5 → 1.0")

    # 序列短于窗口时按实际长度归一（不补零）。
    got3 = dict(check_saturation(["打脸", "打脸"], window=5, threshold=0.6))
    t.eq(round(got3.get("打脸", 0), 4), 1.0, "短序列按实际长度归一（2/2）")

    # 输出按频率降序。
    seq3 = ["打脸", "打脸", "觉醒", "打脸", "觉醒", "觉醒", "觉醒"]
    order = [p for p, _ in check_saturation(seq3, window=7, threshold=0.4)]
    freqs = [f for _, f in check_saturation(seq3, window=7, threshold=0.4)]
    t.eq(freqs, sorted(freqs, reverse=True), "输出按频率降序（确定性）")
    t.ok(len(order) >= 2, "该序列至少有两个装置达到阈值")

    # 阈值边界：恰好等于阈值要报（>= 而不是 >）。
    got4 = dict(check_saturation(["a", "b"], window=2, threshold=0.5))
    t.eq(round(got4.get("a", 0), 4), 0.5, "恰好等于阈值时报（判据是 >=）")


# ---------------------------------------------------------------------------
# 4. 回归：pattern_saturation 在有 storylet 的 IR 上不崩，且显式声明优先
# ---------------------------------------------------------------------------


def _ir_with_storylets(*, declared: list[str], scene_value: str, n_scenes: int = 5):
    """构造一个带 storylet 的 IR：storylet 显式声明装置，场景卡另有文本。

    两边刻意**指向不同的装置**，才能验证「显式声明优先于关键词反推」。
    """
    from loom.ir.devices import ALL_PATTERNS
    from loom.ir.enums import ArcShape, Focalization, Frequency, SceneOutcome
    from loom.ir.models import (
        CommitmentLayer,
        NarrativeIR,
        SceneNode,
        Storylet,
        TimePoint,
    )

    scenes = []
    for i in range(n_scenes):
        scenes.append(
            SceneNode(
                id=f"sc{i + 1}",
                title=f"场景 {i + 1}",
                focalizer="hero",
                narrator="hero",
                focalization=Focalization.INTERNAL,
                fabula_time=TimePoint(day=i),
                sjuzhet_index=i,
                frequency=Frequency.SINGULATIVE,
                value=scene_value,
                value_charge_start="+" if i % 2 == 0 else "-",
                value_charge_end="-" if i % 2 == 0 else "+",
                goal="g",
                conflict="c",
                turning_point="t",
                outcome=SceneOutcome.YES_BUT,
                entities=["hero"],
                # ↓ 关键：storylet_ids 住在**场景**上（这正是当初写错的地方）
                storylet_ids=[f"st{i + 1}"],
            )
        )

    storylets = [
        Storylet(
            id=f"st{i + 1}",
            at_waypoint=f"sc{i + 1}",
            content="x",
            patterns=list(declared),
        )
        for i in range(n_scenes)
    ]

    return NarrativeIR(
        title="t",
        commitment=CommitmentLayer(
            premise="p",
            controlling_idea="c",
            logline="l",
            ending_anchor="e",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
        ),
        scenes=scenes,
        storylets=storylets,
        beat_template=None,
    ), ALL_PATTERNS


def test_storylet_branch_regression(t: T) -> None:
    from loom.ir.devices import infer_patterns
    from loom.validators import get_validator

    t.group("4. 回归：有 storylet 的 IR 上 pattern_saturation 不崩")

    validator = get_validator("pattern_saturation")
    t.ok(validator is not None, "pattern_saturation 已注册")

    # (a) 不崩 —— 这是当初的缺陷点。
    ir, patterns = _ir_with_storylets(
        declared=[patterns_ := "打脸"], scene_value="信任"
    )
    try:
        out = validator(ir)
        t.ok(True, "带 storylet 的 IR 上不抛异常（当初在此崩 AttributeError）")
    except AttributeError as exc:
        t.ok(False, f"带 storylet 的 IR 上抛 AttributeError：{exc}")
        return
    t.ok(isinstance(out, list), "返回 list[Finding]")

    # 该 IR 里 5 场都声明了同一个装置 → 必然饱和。
    codes = {f.code for f in out}
    t.eq(codes, {"pattern_saturation"}, "全部产出都是 pattern_saturation")
    t.ok(bool(out), "5/5 声明同一装置 → 报饱和")
    t.eq(
        {f.evidence["pattern"] for f in out},
        {patterns_},
        "报的正是被声明的那个装置",
    )
    t.ok(
        all(f.severity.value == "warn" for f in out),
        "频率 1.0 ≥ 0.8 → WARN 级",
    )

    # (b) 显式声明**优先于**关键词反推。
    #     场景卡的 value 是「信任」，反推不出来；storylet 声明「打脸」。
    #     若实现误用了反推通道，这里会得到空结果。
    t.eq(infer_patterns("信任"), [], "场景卡文本本身反推不出任何装置")
    t.ok(bool(out), "但显式声明仍然被采纳 —— 声明通道优先")

    # (c) 没有 storylet 时走反推通道，不崩。
    ir2, _ = _ir_with_storylets(declared=[], scene_value="信任")
    ir2.storylets = []
    t.eq(validator(ir2), [], "无 storylet + 文本反推不出装置 → 零输出（不误报）")

    # (d) 反推通道真的会报：把场景 value 换成一个已知装置名。
    ir3, _ = _ir_with_storylets(declared=[], scene_value="打脸")
    ir3.storylets = []
    t.ok(bool(validator(ir3)), "无 storylet 时反推通道生效（5/5「打脸」→ 报饱和）")

    # (e) 证据不足时不判定。
    #     `check_saturation` 的频率分母是「**可识别**场景数」，不是「场景数」。
    #     于是全篇只有 1 场能被认出时频率恒为 1.0，必然 ≥ 阈值 ——
    #     一个只出现了一次的装置会被判成「已饱和」。那不是饱和，是数据不足。
    #     原语只负责算频率，够不够判由校验器决定（见 _PATTERN_MIN_OBSERVATIONS）。
    from loom.validators.structure import _PATTERN_MIN_OBSERVATIONS

    t.ok(_PATTERN_MIN_OBSERVATIONS >= 2, "存在「最少可识别场景数」下限")
    for n in range(1, _PATTERN_MIN_OBSERVATIONS):
        irn, _ = _ir_with_storylets(
            declared=["打脸"], scene_value="信任", n_scenes=n
        )
        t.eq(
            validator(irn),
            [],
            f"只有 {n} 个可识别场景时不判定饱和（证据不足）",
        )
    irm, _ = _ir_with_storylets(
        declared=["打脸"], scene_value="信任", n_scenes=_PATTERN_MIN_OBSERVATIONS
    )
    t.ok(
        bool(validator(irm)),
        f"达到下限（{_PATTERN_MIN_OBSERVATIONS} 个）时正常判定",
    )


# ---------------------------------------------------------------------------
# 5. 单一真源：runtime 只是重新导出，不是第二份实现
# ---------------------------------------------------------------------------


def test_single_source_of_truth(t: T) -> None:
    import loom.ir.devices as D
    import loom.runtime.cooldown as C

    t.group("5. 单一真源：runtime 重新导出，不是第二份实现")

    t.ok(
        C.check_saturation is D.check_saturation,
        "cooldown.check_saturation 与 devices.check_saturation 是**同一个对象**",
    )
    t.ok(
        C.ALL_PATTERNS is D.ALL_PATTERNS,
        "ALL_PATTERNS 是同一个对象（不是拷贝）",
    )
    for name in ("PLEASURE_TYPES", "CONFLICT_TYPES", "EMOTIONAL_ARCS"):
        t.ok(
            getattr(C, name) is getattr(D, name),
            f"{name} 是同一个对象",
        )

    # 事件冷却矩阵上的静态方法必须**委托**，不能自己再实现一遍。
    seq = ["打脸", "打脸", "觉醒", "打脸", "打脸"]
    t.eq(
        C.EventCooldownMatrix.check_saturation(seq, 5, 0.6),
        D.check_saturation(seq, 5, 0.6),
        "矩阵上的静态方法委托给 devices.check_saturation，结果一致",
    )

    # 顺带钉住一条设计边界：**矩阵状态**与**序列饱和**是两件事。
    #   - 冷却值：累计用了多少次（跨场衰减）
    #   - 饱和：最近 window 场里同一装置占比
    # 把它们混成一个指标，会让「一个装置用得多但间隔很长」被误判成饱和。
    m = C.EventCooldownMatrix()
    for _ in range(3):
        m.record_usage("打脸")
    t.eq(m.get_hot_patterns(0.5), [("打脸", 3.0)], "record_usage 累加冷却值（不是覆盖）")
    t.eq(
        m.check_saturation(["觉醒"] * 5, 5, 0.6),
        [("觉醒", 1.0)],
        "静态饱和检测只看传入序列，**不读矩阵状态**（两个指标不串味）",
    )


# ---------------------------------------------------------------------------


def main() -> int:
    t = T()
    test_taxonomy(t)
    test_infer_patterns(t)
    test_check_saturation(t)
    test_storylet_branch_regression(t)
    test_single_source_of_truth(t)

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
