"""四个工艺检测器 —— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**，期望值全部从
四份方法论的原始主张推导，不是从实现里抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_craft.py

零依赖（不用 pytest），与 `tests/test_csn.py` 同风格。

── 期望值的来源 ────────────────────────────────────────

  micro_tension   Maass《Writing the Breakout Novel》：张力不该只挂在情节上，
                  每一段都该有「未解决的摩擦」。**自我抵消**是他点名的反模式：
                  刚拉起的张力被同一段里的流水账/静态描写中和掉。

  control_illusion Peter Storr 的六条叙事控制规则（因果解释延迟 / 模式中断 /
                  视角跳变 / 信息超载 / 无回报 / 细节缺失）—— 违反其中任何一条，
                  读者会觉得「故事不受控」，而不是「角色失控」。

  reality_effect  Barthes「L'effet de réel」：让读者相信世界的不是意义，
                  是那些**无意义的、具体的、感官的**细节（福楼拜的晴雨表）。
                  抽象名词堆砌 = 意义过载而世界缺席。

  show_dont_tell  展示不告知。这是四个里唯一**必须做豁免**的：
                  检出「他很生气」之后要去邻句找「攥紧/青筋/拍桌」这类呈现信号，
                  找得到就**不算违规**。纯命中匹配会把它报成 AI 味，
                  而人类作者写「他很生气，攥紧拳头」完全正常。

── 为什么 A/B 两个用例是这个文件的核心 ──────────────────

`show_dont_tell` 的成败不在「能检出直述」，而在**检出之后敢不敢放过**。
所以下面第 4 组用**同一句直述**配两种邻句：

    A  他很生气，攥紧的拳头砸在桌上，青筋暴起。   → 不报
    B  他很生气，转身走了出去，顺手带上了门。     → 报 1 条

两个用例的直述部分逐字相同，唯一差异是邻句有没有呈现信号。
**只报 B、放过 A 才算对**；两个都报 = 纯命中匹配，等于没实现豁免；
两个都不报 = 漏检。三者里只有一种通过。
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
# 最小 IR 构造（不碰 tests/fixtures.py —— 那是别人在改的文件）
# ---------------------------------------------------------------------------


def _scene(sid: str, prose: str | None, index: int = 0):
    from loom.ir.enums import SceneOutcome
    from loom.ir.models import SceneNode, TimePoint

    return SceneNode(
        id=sid,
        title=sid,
        focalizer="c1",
        narrator="narrator",
        fabula_time=TimePoint(day=index + 1),
        sjuzhet_index=index,
        value="信任",
        value_charge_start="+",
        value_charge_end="-",
        goal="拿到钥匙",
        conflict="守门人拦着",
        turning_point="钥匙断在锁里",
        outcome=SceneOutcome.NO_AND,
        prose=prose,
    )


def _ir(scenes):
    from loom.ir.enums import ArcShape
    from loom.ir.models import CommitmentLayer, NarrativeIR

    return NarrativeIR(
        title="工艺检测器测试",
        commitment=CommitmentLayer(
            premise="贪念必然反噬",
            controlling_idea="想留住的人，最后都是自己推走的",
            logline="刀客收尸时认出自己的名字",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="他把刀留在雪地里",
        ),
        scenes=scenes,
    )


# ---------------------------------------------------------------------------
# 1. micro_tension
# ---------------------------------------------------------------------------


def test_micro_tension(t: T) -> None:
    from loom.audit.craft import micro_tension_findings, scan_micro_tension
    from loom.ir.enums import Severity

    t.group("1. micro_tension（Maass 微张力）")

    # 干净：张力密度够，且没有平淡材料 → 什么都不报
    rep = scan_micro_tension("刀锋贴着喉咙。他攥紧刀柄，心跳如鼓。", scene_id="sc1")
    t.eq(micro_tension_findings(rep), [], "张力充足的段落 → 无结论")

    # 正例 1：纯流水账 → 密度偏低
    flat = "然后他坐了下来，随后看了看窗外。一切如常，日子还是那样平静地流过。"
    fs = micro_tension_findings(scan_micro_tension(flat, scene_id="sc1"))
    t.eq(len(fs), 1, "流水账段落 → 1 条")
    if fs:
        t.eq(fs[0].code, "craft:micro_tension_low", "code")
        t.eq(fs[0].severity, Severity.INFO, "低密度 → INFO（工艺信号噪声大）")
        t.eq(fs[0].scene_id, "sc1", "场次")
        t.ok("张力密度" in fs[0].message, "消息含「张力密度」")

    # 正例 2：自我抵消 —— 张力信号被同段的平淡材料中和
    mixed = (
        "他攥紧刀柄，心跳如鼓，难道这就是结局？"
        "然后他抬头看了看天色，一切如常，日子还是那样平静地流过。"
    )
    fs = micro_tension_findings(scan_micro_tension(mixed, scene_id="sc1"))
    t.eq(len(fs), 1, "张力 + 平淡同段 → 1 条自我抵消")
    if fs:
        t.eq(fs[0].code, "craft:micro_tension_cancel", "code")
        t.eq(fs[0].severity, Severity.WARN, "自我抵消 → WARN（双阈值量化）")
        t.ok("张力自我抵消" in fs[0].message, "消息含「张力自我抵消」")

    # 段落切分：平淡段 + 张力段分开时不产生自我抵消
    two = (
        "他攥紧刀柄，心跳如鼓，难道这就是结局？\n\n"
        "然后他抬头看了看天色，一切如常。日子还是那样平静地流过。"
    )
    rep = scan_micro_tension(two, scene_id="sc1")
    t.eq(len(rep.paragraphs), 2, "空行切出两段")
    t.eq(len(micro_tension_findings(rep)), 1, "分段后只剩低密度 1 条（无自我抵消）")
    t.ok(
        all(f.code == "craft:micro_tension_low" for f in micro_tension_findings(rep)),
        "分段后不再有 cancel",
    )

    t.eq(micro_tension_findings(scan_micro_tension("", scene_id="sc1")), [], "空文本 → 无结论")


# ---------------------------------------------------------------------------
# 2. control_illusion
# ---------------------------------------------------------------------------


def test_control(t: T) -> None:
    from loom.audit.craft import control_findings, scan_control
    from loom.ir.enums import Severity

    def rules(text: str) -> set[str]:
        return {h.rule for h in scan_control(text, scene_id="sc1").hits}

    t.group("2. control_illusion（Storr 六条控制规则）")

    t.eq(
        rules("至于为什么门是开着的，他没有解释。"),
        {"causal_delay"},
        "规则一 因果解释延迟",
    )
    t.eq(
        rules("他走进去，闻到一股霉味。他走向桌子。他走出门外。雨停了。"),
        {"pattern_break"},
        "规则二 模式中断",
    )
    t.eq(
        rules("他抬头看向窗外的光。她低头摆弄衣角。他又把目光收回来。"),
        {"pov_jump"},
        "规则三 视角跳变",
    )
    t.eq(
        rules(
            "《九幽秘典》《太玄真经》《紫府录》分别对应三十六个境界、"
            "七十二种法门、一百零八道符箓，出自三个纪元。"
        ),
        {"info_overload"},
        "规则四 信息超载",
    )
    t.eq(
        rules("他究竟为什么离开，到底是谁带走了那把钥匙，他那时还不知道。"),
        {"no_payoff"},
        "规则五 无回报",
    )
    t.eq(
        rules("他走进房间，坐下，拿起杯子，说了几句话。"),
        {"missing_detail"},
        "规则六 细节缺失",
    )

    # 干净：动作少、有感官通道 → 什么都不报
    clean = "他走进房间，坐下，指尖触到冰凉的杯壁，茶早就凉了。"
    t.eq(rules(clean), set(), "干净文本 → 无命中")
    t.eq(control_findings(scan_control(clean, scene_id="sc1")), [], "干净文本 → 无结论")
    t.eq(control_findings(scan_control("", scene_id="sc1")), [], "空文本 → 无结论")

    # 消息与严重度：单次命中 → INFO
    fs = control_findings(scan_control("至于为什么门是开着的，他没有解释。", scene_id="sc1"))
    t.eq(len(fs), 1, "一条命中 → 一条结论")
    if fs:
        t.eq(fs[0].code, "craft:control:causal_delay", "code")
        t.eq(fs[0].severity, Severity.INFO, "单次命中 → INFO")
        t.ok("因果解释延迟" in fs[0].message, "消息含中文标签")

    # 量化升级：同一条规则命中次数过阈值 → WARN
    fs = control_findings(
        scan_control("《九幽秘典》《太玄真经》《紫府录》分别对应三十六个境界、"
                     "七十二种法门、一百零八道符箓，出自三个纪元。", scene_id="sc1")
    )
    t.eq(len(fs), 1, "信息超载 → 1 条")
    if fs:
        t.eq(fs[0].severity, Severity.WARN, "信息标记 ≥8 → WARN")
        t.ok("信息超载" in fs[0].message, "消息含「信息超载」")

    # 3 连模式中断是 INFO，4 连才升级
    three = "他走进去，闻到一股霉味。他走向桌子。他走出门外。雨停了。"
    fs = control_findings(scan_control(three, scene_id="sc1"))
    t.eq([f.severity for f in fs], [Severity.INFO], "3 连中断 → INFO")
    four = "他走进去，闻到一股霉味。他走向桌子。他走出门外。他走进雨里。天亮了。"
    fs = control_findings(scan_control(four, scene_id="sc1"))
    t.eq([f.severity for f in fs], [Severity.WARN], "4 连中断 → WARN")


# ---------------------------------------------------------------------------
# 3. reality_effect
# ---------------------------------------------------------------------------


def test_reality(t: T) -> None:
    from loom.audit.craft import reality_findings, scan_reality
    from loom.ir.enums import Severity

    t.group("3. reality_effect（Barthes 现实效应）")

    abstract = "命运的意义在于尊严与自由的本质，责任与理想构成精神的全部价值。"
    rep = scan_reality(abstract, scene_id="sc1")
    t.ok(rep.abstract_count >= 6, "抽象名词计数 ≥6")
    t.eq(rep.concrete_count, 0, "无可感具体词")
    fs = reality_findings(rep)
    t.eq(len(fs), 1, "抽象压过可感 → 1 条")
    if fs:
        t.eq(fs[0].code, "craft:reality_effect", "code")
        t.eq(fs[0].severity, Severity.WARN, "抽象 ≥6 且比值 ≥3 → WARN")
        t.eq(fs[0].scene_id, "sc1", "场次")
        t.ok("抽象名词" in fs[0].message, "消息含「抽象名词」")
        t.ok("具体可感" in (fs[0].suggestion or ""), "建议含「具体可感」")

    # 干净 A：纯具体细节（Barthes 意义上的现实效应本体）
    concrete = "他把杯子搁在窗台上，杯壁的水渍在灰尘里留下一圈印子。"
    t.eq(reality_findings(scan_reality(concrete, scene_id="sc1")), [], "纯具体细节 → 无结论")

    # 干净 B：有抽象词，但被具体物压住 → 不报
    grounded = "尊严这东西，说到底就压在肩上的担子和手上的茧里。"
    rep = scan_reality(grounded, scene_id="sc1")
    t.ok(rep.abstract_count < 3, "干净 B：抽象词不足 3")
    t.eq(reality_findings(rep), [], "抽象词少且被具体物压住 → 无结论")

    t.eq(reality_findings(scan_reality("", scene_id="sc1")), [], "空文本 → 无结论")


# ---------------------------------------------------------------------------
# 4. show_dont_tell —— 检测 + 豁免（本文件的核心）
# ---------------------------------------------------------------------------


def test_show_dont_tell(t: T) -> None:
    from loom.audit.craft import scan_show_dont_tell, show_dont_tell_findings
    from loom.ir.enums import Severity

    t.group("4. show_dont_tell —— 豁免用例 A：直述 + 邻句呈现信号")

    with_show = "他很生气，攥紧的拳头砸在桌上，青筋暴起。"
    rep = scan_show_dont_tell(with_show, scene_id="sc1")
    t.eq(len(rep.tells), 1, "A：确实检出了 1 处直述（不是漏检）")
    if rep.tells:
        t.eq(rep.tells[0].category, "愤怒", "A：情绪类别")
        t.eq(rep.tells[0].tell, "生气", "A：直述词")
        t.ok(rep.tells[0].show_signal is not None, "A：命中呈现信号")
    t.eq(len(rep.exempted), 1, "A：被豁免 1 处")
    t.eq(len(rep.violations), 0, "A：违规 0 处")
    t.eq(show_dont_tell_findings(rep), [], "A：有呈现信号 → 不报")

    t.group("5. show_dont_tell —— 豁免用例 B：同一句直述，附近无呈现信号")

    without_show = "他很生气，转身走了出去，顺手带上了门。"
    rep = scan_show_dont_tell(without_show, scene_id="sc1")
    t.eq(len(rep.tells), 1, "B：同样检出 1 处直述")
    t.eq(len(rep.exempted), 0, "B：无豁免")
    t.eq(len(rep.violations), 1, "B：违规 1 处")
    fs = show_dont_tell_findings(rep)
    t.eq(len(fs), 1, "B：无呈现信号 → 报 1 条")
    if fs:
        t.eq(fs[0].code, "craft:tell", "B：code")
        t.eq(fs[0].severity, Severity.INFO, "B：单处直述 → INFO")
        t.eq(fs[0].scene_id, "sc1", "B：场次")
        t.ok("无对应的呈现信号" in fs[0].message, "B：消息含「无对应的呈现信号」")
        t.ok("攥紧" in (fs[0].suggestion or ""), "B：建议给出该情绪的呈现信号示例")

    # A 与 B 的直述部分逐字相同，唯一差异是邻句 —— 这就是「非对称」的证据
    t.ok(
        with_show.replace("攥紧的拳头砸在桌上，青筋暴起", "转身走了出去，顺手带上了门")
        == without_show,
        "A/B 是同一句直述的两种邻句（差异只在邻句）",
    )

    t.group("6. show_dont_tell —— 窗口可配置")

    spread = "他很生气。他站起来。他攥紧了拳头。"
    near = scan_show_dont_tell(spread, scene_id="sc1", window=1)
    t.eq(len(near.violations), 1, "window=1：隔两句的呈现信号够不着 → 违规 1")
    far = scan_show_dont_tell(spread, scene_id="sc1", window=2)
    t.eq(len(far.violations), 0, "window=2：够得着 → 违规 0")
    t.eq(far.tells[0].show_signal, "攥紧", "window=2：记下命中的信号")

    t.group("7. show_dont_tell —— 干净文本与量化升级")

    t.eq(
        show_dont_tell_findings(
            scan_show_dont_tell("他攥紧了拳头，青筋从手背上鼓起来。", scene_id="sc1")
        ),
        [],
        "纯呈现、无直述 → 无结论",
    )
    t.eq(
        show_dont_tell_findings(scan_show_dont_tell("他把钥匙放在桌上。", scene_id="sc1")),
        [],
        "中性叙述 → 无结论",
    )
    t.eq(
        show_dont_tell_findings(scan_show_dont_tell("", scene_id="sc1")),
        [],
        "空文本 → 无结论",
    )

    many = "他很生气。她很生气。大家都很愤怒。"
    fs = show_dont_tell_findings(scan_show_dont_tell(many, scene_id="sc1"))
    t.eq(len(fs), 1, "同情绪聚合为 1 条")
    if fs:
        t.eq(fs[0].severity, Severity.WARN, "同情绪 ≥3 处 → WARN")
        t.ok("×3" in fs[0].message, "消息含 ×3")


# ---------------------------------------------------------------------------
# 5. scan_ir
# ---------------------------------------------------------------------------


def test_scan_ir(t: T) -> None:
    from loom.audit.craft import scan_ir

    t.group("8. scan_ir —— 跨场 + 跳过空 prose")

    abstract = "命运的意义在于尊严与自由的本质，责任与理想构成精神的全部价值。"
    ir = _ir([_scene("sc1", abstract, 0), _scene("sc2", None, 1)])
    fs = scan_ir(ir)
    t.eq(len(fs), 1, "只扫有 prose 的场景 → 1 条")
    if fs:
        t.eq(fs[0].code, "craft:reality_effect", "code")
        t.eq(fs[0].scene_id, "sc1", "结论归给有 prose 的那场")
    t.ok(all(f.scene_id != "sc2" for f in fs), "prose 为 None 的场景被跳过")

    ir2 = _ir([_scene("sc1", None, 0), _scene("sc2", "", 1)])
    t.eq(scan_ir(ir2), [], "prose 全空 → 无结论")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  四个工艺检测器 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_micro_tension(t)
        test_control(t)
        test_reality(t)
        test_show_dont_tell(t)
        test_scan_ir(t)
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
