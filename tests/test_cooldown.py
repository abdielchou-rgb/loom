"""事件冷却矩阵（craft-device cooldown）—— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**。期望值全部从
「指数衰减」的数学定义与「窗口内频率」的字面定义推导，不是从实现里
抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_cooldown.py

零依赖（不用 pytest），与本项目其余部分一致。

── 为什么这个模块值得存在 ──────────────────────────────

Keel 的 Director 已有**逐 storylet** 的节奏冷却，但没有**手法/母题**层面的
冷却。后果：五个不同的 storylet 可以全是「打脸」，而没有任何校验器会发现 ——
`outcome_distribution` 只看 yes/no/yes_but，`mao_repeat_variation` 只看
单场之内的重复。本模块补的正是这个缺口：**生成侧的母题模式约束**。

── 期望值的来源 ────────────────────────────────────────

1. 衰减用 `decay ** steps`（每推进一章/一个 waypoint 乘一次），
   这是指数衰减的**定义**，不是经验参数：
       记录一次 -> 1.0；推进 3 步（decay=0.7）-> 0.7**3 = 0.3429999999999999
   （浮点字面量直接取自 CPython 的 repr，写死在这里以抵抗「改实现改期望」。）

2. `check_saturation` 的频率 = 窗口内出现次数 / 窗口长度
   （窗口不足时除以实际长度）。例：5 章里出现 4 次 -> 4/5 = 0.8。
   边界判据是 **>=**：恰好等于阈值算饱和，「低于阈值」必须**不报**。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 极简断言框架（与 tests/test_csn.py 同风格，不引入 pytest）
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
# 1. 衰减数学：decay ** steps 的精确性
# ---------------------------------------------------------------------------


def test_decay(t: T) -> None:
    from keel.runtime.cooldown import EventCooldownMatrix

    t.group("1. 指数衰减（decay ** steps）")

    m = EventCooldownMatrix()  # 默认 decay=0.7
    m.record_usage("打脸")
    t.eq(m.get_cooldown("打脸"), 1.0, "记录一次 -> 1.0")

    m.advance_time()  # steps 默认 1
    t.eq(m.get_cooldown("打脸"), 0.7, "推进 1 步 -> 0.7**1")

    m.advance_time(2)  # 累计 3 步
    t.eq(m.get_cooldown("打脸"), 0.3429999999999999, "累计 3 步 -> 0.7**3")

    # 自定义 decay：0.5**3 = 0.125（二进制可精确表示，正好用来钉死乘法顺序）
    m2 = EventCooldownMatrix(decay=0.5)
    m2.record_usage("碾压")
    m2.advance_time(3)
    t.eq(m2.get_cooldown("碾压"), 0.125, "decay=0.5，3 步 -> 0.125")

    # decay=1.0 时完全不衰减（可配置性的一条边界）
    m3 = EventCooldownMatrix(decay=1.0)
    m3.record_usage("甜")
    m3.advance_time(5)
    t.eq(m3.get_cooldown("甜"), 1.0, "decay=1.0 -> 不衰减")

    # advance_time 必须作用于**全部**已记录的模式
    m4 = EventCooldownMatrix()
    m4.record_usage("打脸")
    m4.record_usage("逆袭")
    m4.advance_time()
    t.eq(m4.get_cooldown("打脸"), 0.7, "衰减作用于打脸")
    t.eq(m4.get_cooldown("逆袭"), 0.7, "衰减作用于逆袭")

    # 未记录过的模式：冷却为 0.0（不是 KeyError，也不是 None）
    t.eq(m.get_cooldown("从未用过的手法"), 0.0, "未记录 -> 0.0")


# ---------------------------------------------------------------------------
# 2. record_usage 累加
# ---------------------------------------------------------------------------


def test_record_usage(t: T) -> None:
    from keel.runtime.cooldown import EventCooldownMatrix

    t.group("2. record_usage 累加")

    m = EventCooldownMatrix()
    for _ in range(3):
        m.record_usage("打脸")
    t.eq(m.get_cooldown("打脸"), 3.0, "记录三次 -> 3.0")

    # 不同模式互不干扰
    m.record_usage("觉醒")
    t.eq(m.get_cooldown("打脸"), 3.0, "打脸不受觉醒影响")
    t.eq(m.get_cooldown("觉醒"), 1.0, "觉醒独立计数")

    # 衰减后再记录 = 衰减值 + 1.0（不是清零后重来）
    m.advance_time()
    m.record_usage("觉醒")
    t.eq(m.get_cooldown("觉醒"), 1.7, "0.7 衰减 + 再记一次 = 1.7")


# ---------------------------------------------------------------------------
# 3. get_hot_patterns / get_recommendations
# ---------------------------------------------------------------------------


def test_hot_and_recommendations(t: T) -> None:
    from keel.runtime.cooldown import EventCooldownMatrix

    t.group("3. 热点模式与推荐（排序与阈值）")

    m = EventCooldownMatrix()
    for _ in range(4):
        m.record_usage("打脸")
    for _ in range(2):
        m.record_usage("觉醒")

    # 热点：降序；阈值判据是 >=
    hot = m.get_hot_patterns(0.5)
    t.eq(hot, [("打脸", 4.0), ("觉醒", 2.0)], "热点按冷却降序")

    t.eq(m.get_hot_patterns(2.5), [("打脸", 4.0)], "阈值 2.5 排除觉醒(2.0)")
    t.eq(
        m.get_hot_patterns(2.0),
        [("打脸", 4.0), ("觉醒", 2.0)],
        "阈值 2.0 恰好包含觉醒（边界 >=）",
    )
    t.eq(m.get_hot_patterns(5.0), [], "阈值高于所有值 -> 空")

    # 推荐：全分类学里冷却最低的 3 个；没用过的模式冷却为 0，因此优先被推荐
    recs = m.get_recommendations(3)
    t.eq(recs, ["碾压", "降维打击", "逆袭"], "推荐 = 分类学序中最低冷却的三个")
    t.ok("打脸" not in recs, "过热的打脸不得出现在推荐里")
    t.ok("觉醒" not in recs, "已用过的觉醒不得出现在推荐里")

    # 冷启动：空矩阵也应给出建议（分类学前三个）
    t.eq(
        EventCooldownMatrix().get_recommendations(3),
        ["打脸", "碾压", "降维打击"],
        "空矩阵冷启动推荐",
    )

    # 再热一个模式，推荐顺位应后移
    m.record_usage("碾压")
    m.record_usage("碾压")
    m.record_usage("碾压")
    t.eq(m.get_recommendations(1), ["降维打击"], "碾压变热后不再被推荐")


# ---------------------------------------------------------------------------
# 4. check_saturation：窗口化重复（可独立用于线性叙事）
# ---------------------------------------------------------------------------


def test_saturation(t: T) -> None:
    from keel.runtime.cooldown import EventCooldownMatrix

    t.group("4. check_saturation 窗口化重复")

    # 独立静态调用：不需要实例，可对任意线性叙事序列使用
    sat = EventCooldownMatrix.check_saturation

    # 5 章里出现 4 次 -> 80%，超阈值 0.6
    seq = ["打脸", "打脸", "觉醒", "打脸", "打脸"]
    t.eq(sat(seq, window=5, threshold=0.6), [("打脸", 0.8)], "5 章 4 次 -> 0.8 报出")

    # 边界：恰好 3/5 = 0.6 -> 判据是 >=，必须报出
    seq = ["打脸", "觉醒", "打脸", "碾压", "打脸"]
    t.eq(sat(seq, window=5, threshold=0.6), [("打脸", 0.6)], "恰好 0.6 -> 报出（>=）")

    # 边界：2/5 = 0.4 < 0.6 -> 必须**不报**
    seq = ["打脸", "觉醒", "打脸", "碾压", "突破"]
    t.eq(sat(seq, window=5, threshold=0.6), [], "0.4 低于阈值 -> 不报")

    # 只看最后 window 个：早期的密集重复若已滑出窗口，不该继续报警
    seq = ["打脸", "打脸", "打脸", "打脸", "打脸", "觉醒", "觉醒", "碾压", "突破", "甜"]
    t.eq(sat(seq, window=5, threshold=0.6), [], "重复已滑出窗口 -> 不报")

    # 序列短于窗口时，分母取实际长度：两章都是打脸 = 100%
    t.eq(sat(["打脸", "打脸"], window=5, threshold=0.6), [("打脸", 1.0)], "短序列按实际长度归一")

    # 多个饱和项按频率降序
    seq = ["打脸", "打脸", "打脸", "觉醒", "觉醒"]
    t.eq(
        sat(seq, window=5, threshold=0.4),
        [("打脸", 0.6), ("觉醒", 0.4)],
        "多个饱和项按频率降序",
    )

    # 空序列
    t.eq(sat([], window=5, threshold=0.6), [], "空序列 -> 空")


# ---------------------------------------------------------------------------
# 5. Director 向后兼容不变量（空 patterns ⇒ 分数完全不变）
# ---------------------------------------------------------------------------


def _plain_storylet(**kw):
    from keel.ir.models import Storylet

    return Storylet(id="s1", content="正文", salience=1.0, **kw)


def test_director_backward_compat(t: T) -> None:
    from keel.ir.models import Storylet
    from keel.runtime.cooldown import EventCooldownMatrix
    from keel.runtime.director import Director, RuntimeState

    t.group("5. 向后兼容：空 patterns 分数不变")

    s = Storylet(id="s1", content="正文", salience=1.0)
    t.eq(s.patterns, [], "patterns 默认为空列表")

    d_no = Director("rags_to_riches")
    d_with = Director("rags_to_riches", cooldown=EventCooldownMatrix())

    sel_no = d_no.score(s, RuntimeState(), 0.5)
    sel_with = d_with.score(s, RuntimeState(), 0.5)

    # 精确相等，不是「差不多」——新增项在空 patterns 下增量必须是 0.0
    t.eq(sel_with.score, sel_no.score, "空 patterns：带矩阵与不带矩阵分数一致")
    t.eq(sel_no.score, 0.9, "基线分数 = salience 1.0 - 0.1（不推进节拍）")

    # 矩阵为 None 时同样不变
    d_none = Director("rags_to_riches", cooldown=None)
    t.eq(d_none.score(s, RuntimeState(), 0.5).score, sel_no.score, "cooldown=None 分数一致")

    # 空 patterns 不得追加装置冷却理由
    t.ok("装置冷却" not in sel_with.reason, "空 patterns 不产生装置冷却理由")

    # 带 patterns 但矩阵为 None：仍不得改变分数
    s2 = _plain_storylet(patterns=["打脸"])
    t.eq(d_none.score(s2, RuntimeState(), 0.5).score, sel_no.score, "矩阵为 None 时不惩罚")


# ---------------------------------------------------------------------------
# 6. Director 净效应不变量（热模式严格低于冷模式）
# ---------------------------------------------------------------------------


def test_director_net_effect(t: T) -> None:
    from keel.runtime.cooldown import EventCooldownMatrix
    from keel.runtime.director import Director, RuntimeState

    t.group("6. 净效应：热模式严格降权")

    m = EventCooldownMatrix()
    for _ in range(4):
        m.record_usage("打脸")

    d = Director("rags_to_riches", cooldown=m, pattern_penalty=0.35)
    state = RuntimeState()

    hot = _plain_storylet(patterns=["打脸"])
    cold = _plain_storylet(patterns=["觉醒"])

    sel_hot = d.score(hot, state, 0.5)
    sel_cold = d.score(cold, state, 0.5)

    t.ok(sel_hot.score < sel_cold.score, "热模式分数严格低于冷模式")
    t.eq(sel_cold.score, 0.9, "冷模式（冷却 0）分数不变 = 0.9")
    t.eq(sel_hot.score, -0.4999999999999999, "热模式 = 0.9 - 0.35*4.0")
    t.ok("装置冷却" in sel_hot.reason, "热模式理由里出现装置冷却")
    # 冷模式（有 patterns、有矩阵）仍按约定追加理由，但惩罚为 0.00
    t.ok("装置冷却-0.00" in sel_cold.reason, "冷模式理由是 0.00（不改变分数）")

    # 多模式取均值：(["打脸","觉醒"] 冷却 4 与 0) -> 均值 2.0 -> 惩罚 0.7
    multi = _plain_storylet(patterns=["打脸", "觉醒"])
    t.eq(d.score(multi, state, 0.5).score, 0.20000000000000007, "多模式取冷却均值")

    # 自定义惩罚系数确实生效
    d2 = Director("rags_to_riches", cooldown=m, pattern_penalty=1.0)
    t.eq(d2.score(hot, state, 0.5).score, 0.9 - 4.0, "pattern_penalty=1.0 生效")


# ---------------------------------------------------------------------------
# 7. StoryRuntime 接线：记录 / 衰减 / 暴露矩阵
# ---------------------------------------------------------------------------


def _minimal_ir():
    from keel.ir.enums import ArcShape, SceneOutcome
    from keel.ir.models import (
        CommitmentLayer,
        NarrativeIR,
        SceneNode,
        Storylet,
        TimePoint,
    )

    def scene(i: int, sid: str) -> SceneNode:
        return SceneNode(
            id=sid,
            title=sid,
            focalizer="hero",
            narrator="narrator",
            fabula_time=TimePoint(day=i),
            sjuzhet_index=i,
            value="信任",
            value_charge_start="-",
            value_charge_end="+",
            goal="目标",
            conflict="阻碍",
            turning_point="转折",
            outcome=SceneOutcome.YES_BUT,
        )

    return NarrativeIR(
        title="冷却接线测试",
        commitment=CommitmentLayer(
            premise="前提",
            controlling_idea="控制理念",
            logline="一句话",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="结局锚点",
        ),
        scenes=[scene(0, "wp1"), scene(1, "wp2")],
        storylets=[
            Storylet(
                id="sl1",
                content="正文",
                salience=1.0,
                patterns=["打脸"],
                repeatable=True,
            )
        ],
    )


def test_runtime_wiring(t: T) -> None:
    from keel.runtime.director import StoryRuntime

    t.group("7. StoryRuntime 接线")

    rt = StoryRuntime(_minimal_ir(), seed=0)
    t.ok(rt.cooldown is not None, "运行时暴露冷却矩阵")

    sel = rt.next_storylet()
    t.eq(sel.storylet.id, "sl1", "选中唯一合法块")
    t.eq(rt.cooldown.get_cooldown("打脸"), 1.0, "选中后记录一次模式使用")

    rt.advance_waypoint()
    t.eq(rt.cooldown.get_cooldown("打脸"), 0.7, "推进 waypoint 后衰减 0.7")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  事件冷却矩阵 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_decay(t)
        test_record_usage(t)
        test_hot_and_recommendations(t)
        test_saturation(t)
        test_director_backward_compat(t)
        test_director_net_effect(t)
        test_runtime_wiring(t)
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
