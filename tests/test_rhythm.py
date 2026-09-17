"""三个平台合规检测器的单元测试。

跑法：
    .venv/Scripts/python.exe tests/test_rhythm.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `test_dress.py` 同风格。

── 关于纪律的一句实话 ─────────────────────────────────────

`loom/audit/rhythm.py` 是先实现的，本文件**后写** —— 这不是 TDD。
为此做了补偿：六个阈值常量全部被**变异测试**过 —— 把每个改成一个永不
（或恒）触发的值，确认本文件变红。没有这一步，「测试全绿」只说明测试与
实现一致，不说明测试测到了东西。实测结果（六个全部 RED）：

    _ADVERB_PARAGRAPH_LIMIT → 1000    第 4 组
    _BARE_RUN_MIN           → 99      第 5 组
    _SCENE_DEVIATION_MAX    → -1.0    第 2 组
    _BURST_SENTENCE_MIN     → -99.0   第 3 组
    _BURST_MIN_SENTENCES    → 1       第 3 组
    _BURST_MIN_SCENES       → 1       第 2 组

**第 2、3 组是必需的，不是凑数**：`scripts/verify.py` 的 4d 检查在
`_SCENE_DEVIATION_MAX` / `_BURST_SENTENCE_MIN` 被改坏时**单独看是绿的** ——
因为反例变异同时触发爆发度的**两个轴**，杀掉任何一个轴，另一个轴还在说话，
于是「advisory 项真的会产出」依然成立。这是**轴间掩盖**：
`verify.py` 按 code 判，不按 evidence 判，结构上抓不到它。
现在它靠第 8 节跑本文件兜住（实测也是 RED），但**兜住它的是这里，不是那里**。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

    def close(self, got: float, want: float, label: str, tol: float = 1e-6) -> None:
        if abs(got - want) <= tol:
            self.passed += 1
        else:
            self.failed.append(f"{label}\n      期望 {want!r}±{tol}\n      实际 {got!r}")

    def group(self, name: str) -> None:
        print(f"\n  {name}")


# ---------------------------------------------------------------------------
# 共享样本
# ---------------------------------------------------------------------------

#: 等长句单元：一句 10 字。重复它会让**两个轴同时塌**
#: （场长相等 + 句长相等），这也是 `tests/fixtures.py` 里那个变异用的同一串。
_UNIFORM_UNIT = "他走进院子，停了一下。"


class _Scene:
    def __init__(self, id: str, prose: str) -> None:
        self.id = id
        self.prose = prose


class _IR:
    """最小 IR 桩件。三个检测器只碰 `ordered_scenes()` 与 `prose`，
    不需要真 IR（也就不需要 pydantic，保持零依赖）。"""

    def __init__(self, scenes: list[_Scene]) -> None:
        self.scenes = scenes

    def ordered_scenes(self) -> list[_Scene]:
        return self.scenes


# ---------------------------------------------------------------------------
# 1. 爆发度系数本身
# ---------------------------------------------------------------------------


def test_burstiness_coefficient(t: T) -> None:
    from loom.audit.rhythm import burstiness

    t.group("1. 爆发度系数 B = (σ − μ) / (σ + μ)")

    t.close(burstiness([1.0, 1.0, 1.0, 1.0]), -1.0, "完全均匀 → B = −1（下界）")
    t.eq(burstiness([]), 0.0, "空输入 → 0（无可判离散度，不是 NaN）")
    t.eq(burstiness([0.0, 0.0]), 0.0, "全零（均值 0）→ 0，不炸除零")

    # 手工样本：mean=10, sd=7 → (7−10)/(7+10)
    t.close(burstiness([3.0, 17.0]), (7 - 10) / (7 + 10), "两值样本")

    # 重尾 → B 转正。这是「爆发」的方向，必须与均匀方向相反。
    t.ok(burstiness([1.0, 1.0, 1.0, 1.0, 10.0]) > 0, "一个离群长句 → B > 0")

    # 单调性：同一个序列里把离群值拉得更远，B 必须上升。
    # 这条断言钉死的是**方向**，不是一个具体数字 ——
    # 任何把 B 写成 (μ−σ)/(μ+σ) 的实现都会在这里失败。
    b1 = burstiness([1.0, 1.0, 1.0, 1.0, 10.0])
    b2 = burstiness([1.0, 1.0, 1.0, 1.0, 40.0])
    t.ok(b2 > b1, f"离群越远 B 越大（{b1:.3f} → {b2:.3f}）")


# ---------------------------------------------------------------------------
# 2. 场长轴 —— 番茄的「章节字数高度均等（±5%）」
# ---------------------------------------------------------------------------


def test_scene_axis(t: T) -> None:
    from loom.audit.rhythm import burstiness_findings, scan_burstiness

    t.group("2. 场长轴（±5% 口径）")

    equal = scan_burstiness(["字" * 100 for _ in range(5)])
    t.eq(equal.scene_lengths, [100] * 5, "场长原样保留在报告里")
    t.eq(equal.scene_max_deviation, 0.0, "等长 → 最大偏离 0")
    t.close(equal.scene_burstiness, -1.0, "等长 → 爆发度 −1")
    t.ok(equal.uniform_scenes, "5 场全部等长 → 判为均匀")

    # 真实形态的场长（取自干净基线的实际分布）：最大偏离 34%
    varied = scan_burstiness(["字" * n for n in (228, 121, 211, 146, 215, 185)])
    t.close(varied.scene_max_deviation, 0.344, "最大偏离 34.4%（≈63/184）", tol=1e-3)
    t.ok(not varied.uniform_scenes, "偏离远超 5% → 不判均匀")

    # 刚好卡在 5% 边界：**等于**阈值算均匀（口径是「在 ±5% 内」）
    on_edge = scan_burstiness(["字" * 100, "字" * 105, "字" * 100, "字" * 95])
    t.close(on_edge.scene_max_deviation, 0.05, "最大偏离恰好 5%", tol=1e-6)
    t.ok(on_edge.uniform_scenes, "卡在 5% 边界 → 判为均匀（闭区间）")

    # 少于 3 场不判：两场比不出分布
    two = scan_burstiness(["字" * 100, "字" * 100])
    t.eq(len(two.scene_lengths), 2, "两场也在报告里")
    t.ok(not two.uniform_scenes, "少于 3 场 → 不判（分布需要样本量）")

    empty = scan_burstiness([])
    t.eq(empty.scene_count, 0, "无正文 → 空报告")
    t.ok(not empty.uniform_scenes, "无正文 → 不判（不是「均匀」）")

    # 轴标记：场长与句长共用一个 code，靠 evidence["axis"] 区分
    fs = burstiness_findings(equal)
    t.eq([f.evidence["axis"] for f in fs], ["scene"], "等长场只触发场长轴")


# ---------------------------------------------------------------------------
# 3. 句长轴
# ---------------------------------------------------------------------------


def test_sentence_axis(t: T) -> None:
    from loom.audit.rhythm import burstiness_findings, scan_burstiness

    t.group("3. 句长轴")

    flat = scan_burstiness([_UNIFORM_UNIT * 12])
    t.eq(flat.sentence_count, 12, "12 句")
    t.close(flat.sentence_burstiness, -1.0, "等长句 → B = −1")
    t.ok(flat.uniform_sentences, "等长句 + 句数达标 → 判为均匀")

    # 句子数下限：8 句。少于它，CV 本身噪声过大，
    # **哪怕分布完全等长也不判** —— 拿 6 句话算方差，得到的数字只反映这
    # 6 句话，不反映作者。
    #
    # 这一组与上面那组的**唯一差别就是句数**，故它同时钉死了两件事：
    # 下限生效，且下限不是靠「等长」混过去的。
    short = scan_burstiness([_UNIFORM_UNIT * 6])
    t.eq(short.sentence_count, 6, "6 句")
    t.close(short.sentence_burstiness, -1.0, "分布同样完全等长（B = −1）")
    t.eq(short.sentence_cv, flat.sentence_cv, "两个样本的 CV 完全一样")
    t.ok(
        not short.uniform_sentences,
        "句数不足下限 → 不判（与上一组的唯一差别是句数）",
    )

    # 真实形态：干净基线的句长分布 CV≈0.745 → 不判。
    # 这一条防的是「检测器对着正常文本乱报」。
    natural = (
        "她先开的口。\n"
        "他把手按在门框上，停了很久才推开。"
        "雪落在檐下化成了水，水顺着瓦沟流下去，在台阶上结了一层薄冰，"
        "谁踩上去都会滑一下，谁都不会承认自己滑过。\n"
        "院子里的脚印一直延伸到墙根，然后消失。\n"
        "他要的是拿到信任的确认。\n"
        "她把碗推到他面前，没有看他。\n"
        "他说好。\n"
        "她没问为什么。\n"
    )
    nat = scan_burstiness([natural])
    t.ok(not nat.uniform_sentences, f"自然文本不判均匀（B={nat.sentence_burstiness}）")

    fs = burstiness_findings(flat)
    axes = sorted(f.evidence["axis"] for f in fs)
    t.ok("sentence" in axes, "句长轴出现在 evidence 里")


# ---------------------------------------------------------------------------
# 4. 高频副词密度
# ---------------------------------------------------------------------------


def test_adverbs(t: T) -> None:
    from loom.audit.rhythm import adverb_findings, scan_adverbs

    t.group("4. 高频副词密度（> 4 次/段）")

    five = scan_adverbs("他极其愤怒，异常冷静，十分缓慢，格外小心，无比沉默。", "s1")
    t.eq(five.total, 5, "5 个命中")
    t.ok(bool(five.flagged), "5 > 4 → 标记")
    t.eq(len(adverb_findings(five)), 1, "产出一条结论")
    t.eq(
        adverb_findings(five)[0].evidence["by_category"],
        {"程度强化": 5},
        "命中按类别归因",
    )

    # 阈值是「**超过** 4」—— 正好 4 个不算。这条边界必须钉死：
    # 差一个就是「正常行文」与「平台可疑」的区别。
    four = scan_adverbs("他极其愤怒，异常冷静，十分缓慢，格外小心。", "s1")
    t.eq(four.total, 4, "4 个命中")
    t.eq(four.flagged, [], "正好 4 → 不标记（判据是超过）")

    one = scan_adverbs("他极其愤怒。", "s1")
    t.ok(not one.flagged, "1 个副词不是问题 —— 判据是密度不是出现")

    # 逐段判：一段超标不影响另一段（段落是网文的天然单位）
    two_paras = scan_adverbs(
        "他极其愤怒，异常冷静，十分缓慢，格外小心，无比沉默。\n他就走了。",
        "s1",
    )
    t.eq(len(two_paras.paragraphs), 2, "切成两段")
    t.eq([p.index for p in two_paras.flagged], [0], "只有第一段超标")

    # 空输入
    t.eq(scan_adverbs("", "s1").total, 0, "空文本 → 0 命中")
    t.eq(scan_adverbs("", "s1").density, 0.0, "空文本 → 密度 0（不除零）")


# ---------------------------------------------------------------------------
# 5. 对话节奏
# ---------------------------------------------------------------------------


def test_dialogue_rhythm(t: T) -> None:
    from loom.audit.rhythm import dialogue_rhythm_findings, scan_dialogue_rhythm

    t.group("5. 对话节奏（一问一答工整无打断）")

    neat = "「你来了？」\n「来了。」\n「东西呢？」\n「在这儿。」\n「确定？」\n「确定。」"
    r = scan_dialogue_rhythm(neat, "s1")
    t.eq(r.turn_count, 6, "6 轮")
    t.eq(r.bare_run, 6, "6 轮之间没有叙述间隔")
    t.eq(r.qa_pairs, 3, "3 组问→答")
    t.eq(r.interruption_count, 0, "无打断标记")
    t.ok(r.monotonic, "工整无打断 → 判为模板化对话")
    t.eq(len(dialogue_rhythm_findings(r)), 1, "产出一条结论")

    # 有叙述间隔 → 不是裸跑
    with_narration = (
        "「你来了？」她抬起头。\n「来了。」他把包袱放下。\n"
        "「东西呢？」\n「在这儿。」"
    )
    r2 = scan_dialogue_rhythm(with_narration, "s1")
    t.eq(r2.bare_run, 2, "最长裸跑只有 2 轮")
    t.ok(not r2.monotonic, "有叙述间隔 → 不判")

    # 有打断标记 → 不判，哪怕仍然连续裸跑。
    # 这两个条件缺一不可：作者**写了**打断就不是模板。
    r3 = scan_dialogue_rhythm(neat + "\n她打断了他。", "s1")
    t.eq(r3.bare_run, 6, "裸跑仍是 6 轮")
    t.eq(r3.interruption_count, 1, "但有一个打断标记")
    t.ok(not r3.monotonic, "有打断标记 → 不判")

    # 少于 4 轮 → 不判
    r4 = scan_dialogue_rhythm("「你来了？」\n「来了。」\n「东西呢？」", "s1")
    t.eq(r4.bare_run, 3, "3 轮")
    t.ok(not r4.monotonic, "3 轮 < 下限 → 不判（两三句紧凑对白是正常的）")

    # 无对话 → 不判，且**不是**「通过」
    r5 = scan_dialogue_rhythm("他走进院子，停了一下。", "s1")
    t.ok(not r5.has_dialogue, "无引号 → 认不出对话")
    t.ok(not r5.monotonic, "无对话 → 不判")
    t.eq(scan_dialogue_rhythm("", "s1").turn_count, 0, "空文本 → 0 轮")


# ---------------------------------------------------------------------------
# 6. 严重度政策：一律 INFO（这是它们能进 REPORTS/ADVISORY 的前提）
# ---------------------------------------------------------------------------


def test_severity_policy(t: T) -> None:
    from loom.ir.enums import Severity
    from loom.audit.rhythm import scan_ir

    t.group("6. 严重度政策")

    # 对抗性输入：三个缺陷同时拉满。
    #
    # **为什么分成两个 IR**：爆发度的两个轴（场长 / 句长）判的都是
    # 「分布均匀」，而副词段与对白段会往文本里注入**不等长**的句子，
    # 反而把爆发度治好了 —— 塞进同一个 IR 会让三个检测器互相抵消，
    # 只剩一条结论，看起来像「严重度政策通过了」，其实是**没测到**。
    # 3 场而不是 2 场：场长轴要求 ≥3 场才判（两场比不出分布）。
    uniform = _IR(
        [_Scene(f"s{i}", _UNIFORM_UNIT * 12) for i in range(1, 4)]
    )
    crafted = _IR(
        [
            _Scene(
                "s1",
                "他极其愤怒，异常冷静，十分缓慢，格外小心，无比沉默。\n"
                "「你来了？」\n「来了。」\n「东西呢？」\n「在这儿。」\n"
                "「确定？」\n「确定。」",
            )
        ]
    )
    fs = scan_ir(uniform) + scan_ir(crafted)
    codes = sorted(f.code for f in fs)
    t.eq(
        codes,
        ["adverb_density", "dialogue_rhythm", "length_burstiness", "length_burstiness"],
        f"四个判据全部触发（实际 {codes}）",
    )
    t.eq(
        sorted(f.evidence["axis"] for f in fs if f.code == "length_burstiness"),
        ["scene", "sentence"],
        "爆发度的**两个轴**都触发（不是只报一个）",
    )
    worst = {f.severity for f in fs}
    t.eq(worst, {Severity.INFO}, "**没有一条**超过 INFO")

    # 无关输入：不产出
    t.eq(scan_ir(_IR([])), [], "无正文 → 空（不是「通过」）")
    t.eq(scan_ir(_IR([_Scene("s1", "")])), [], "空 prose → 空")


# ---------------------------------------------------------------------------
# 7. 注册分类（可机检，不是口头承诺）
# ---------------------------------------------------------------------------


def test_registration(t: T) -> None:
    from loom.validators import ADVISORY, ADVISORY_DEFECT, REPORTS

    t.group("7. 注册分类")

    codes = ("length_burstiness", "adverb_density", "dialogue_rhythm")
    for code in codes:
        t.ok(code in REPORTS, f"{code} ∈ REPORTS（不可能是门禁）")
        t.ok(code in ADVISORY, f"{code} ∈ ADVISORY（不进健康分）")
        t.ok(code in ADVISORY_DEFECT, f"{code} ∈ ADVISORY_DEFECT（缺陷型）")

    t.ok(ADVISORY_DEFECT <= ADVISORY, "ADVISORY_DEFECT ⊆ ADVISORY")
    t.ok(ADVISORY <= REPORTS, "ADVISORY ⊆ REPORTS")


def main() -> int:
    print("═" * 64)
    print("  平台合规检测器（爆发度 / 副词密度 / 对话节奏）—— 测试")
    print("═" * 64)
    t = T()
    try:
        test_burstiness_coefficient(t)
        test_scene_axis(t)
        test_sentence_axis(t)
        test_adverbs(t)
        test_dialogue_rhythm(t)
        test_severity_policy(t)
        test_registration(t)
    except ImportError as exc:
        print(f"\n  ✗ 模块尚不存在：{exc}")
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
