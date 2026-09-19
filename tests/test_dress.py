"""DRESS 风格漂移三维检测 —— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**，期望值全部从
风格计量学的原始主张推导，不是从实现里抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_dress.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `tests/test_craft.py` 同风格。

── 为什么这个模块值得存在 ──────────────────────────────

Keel 现在只用「提示词版本 + `model_id` 溯源」保证风格一致 —— 记录的是
文本**怎么产生的**，没有测量风格**是否真的漂移了**。
「换了模型但风格没变」于是成为一句没有证据的宣称。

── 三维公式 ─────────────────────────────────────────────

    overall_authenticity = style_fidelity × content_independence × fluency
    passed = overall_authenticity >= 1 - threshold        # 默认 threshold = 0.15

── 为什么 content_independence 才是关键那一维 ────────────

风格保真度只有在**内容也变了**的前提下才有信息量。
若第 2 章讲的还是第 1 章那些事，「听起来一样」是理所当然的 ——
这时候的高 fidelity 什么都没证明。

所以 `content_independence` 要能识别并**折价**这种情况：它衡量的是
「内容明明不同，风格相似性却依然成立」。

    同一内容对    → 独立性低（相似性被内容解释掉了）
    异内容同风格对 → 独立性高（相似性无法被内容解释）

这个**非对称**是本模块的全部价值。第 4 组用同一对文本把它钉死：
两对的 `style_fidelity` 完全相同，唯一差异是 `content_independence`。
一个对两种情况返回同一个值的实现是**失败**的，哪怕其余测试全绿。

── 期望值的来源 ─────────────────────────────────────────

  function-word 风格指纹   Mosteller & Wallace《Inference and Disputed
                          Authorship: The Federalist》(1964)：功能词频率是
                          作者风格最稳的指纹 —— 作者无法自觉控制功能词。

  Delta / 风格距离          Burrows, "Delta: a Measure of Stylistic Difference
                          and a Guide to Authorship Attribution",
                          Literary and Linguistic Computing 17(3), 2002.

  离群鲁棒性                Leys et al., "Detecting outliers: Do not use
                          standard deviation around the mean, use absolute
                          deviation around the median", J. Exp. Soc. Psychol.
                          49(4), 2013 —— 中位数基线比均值稳健。

  （DRESS 这个三维复合公式是 Keel 自己的构造，建立在上述来源之上；
   不存在一篇叫 DRESS 的论文，这里如实标注，不虚构出处。）

── 为什么基线用「剔除 2σ 离群后的中位数」而不是均值 ──────

一章动作戏、一章闪回，句长分布会极端偏离。均值会被它拖走，
中位数不会。第 2 组注入一章极端离群，**同时**报出中位数与均值的
实际数字，证明前者几乎不动、后者被拖走 >10。
"""

from __future__ import annotations

import statistics
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
# 共享样本
# ---------------------------------------------------------------------------

#: 三章「同风格、异内容」。构造约束（刻意让三章的特征向量完全一致）：
#:   句长序列都是 [6, 6, 5, 5]  →  mean=5.5, cv=0.0909
#:   每章恰好 1 个「了」+ 2 个「着」→ particle_ratio=3/22=0.1364
#:   无逗号、无对话、无叹/问号
#: 内容字符二元组两两不相交 → 内容独立性应为 1。
CH_A = "陈默走进客栈。他要了一碗面。他低头吃着。窗外下着雨。"
CH_B = "沈砚推开柴门。她讨了半壶酒。她抬手斟着。檐角挂着雪。"
CH_C = "老卒拖过长枪。他磨了半日刀。弓弦绷着雪。帐外落着霜。"

#: 漂移章：两个长句、逗号密集 —— 与上面三章的风格截然不同。
LONG_CHAPTER = (
    "他站在那条望不到尽头的长街上，回想起许多年前那个下着大雪的清晨，"
    "心里忽然涌起一种说不清道不明的酸楚。"
    "那些年他走过的路、见过的人、说过的谎，都随着这场雪一起落了下来，"
    "落进他再也回不去的旧梦里。"
)

#: 风格距离用的极端对照：短句 vs 长句。
SHORT_SENTENCES = "他走了。她来了。天黑了。雨停了。"
LONG_SENTENCE = "他慢慢地走过那条很长很长的走廊。"


# ---------------------------------------------------------------------------
# 最小 IR 构造（不碰 tests/fixtures.py —— 那是别人在改的文件）
# ---------------------------------------------------------------------------


def _scene(sid: str, prose: str | None, index: int = 0):
    from keel.ir.enums import SceneOutcome
    from keel.ir.models import SceneNode, TimePoint

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
    from keel.ir.enums import ArcShape
    from keel.ir.models import CommitmentLayer, NarrativeIR

    return NarrativeIR(
        title="风格漂移测试",
        commitment=CommitmentLayer(
            premise="贪念必然反噬",
            controlling_idea="想留住的人，最后都是自己推走的",
            logline="刀客收尸时认出自己的名字",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="他把刀留在雪地里",
        ),
        scenes=scenes,
    )


def _prose_ir(chapters: list[str]):
    return _ir([_scene(f"sc{i + 1}", text, i) for i, text in enumerate(chapters)])


def _prof(msl: float) -> "StyleProfile":
    """构造一个只有句长均值在变的档案，其余特征恒定 —— 隔离中位数逻辑。"""
    from keel.audit.dress import StyleProfile

    return StyleProfile(
        mean_sentence_len=msl,
        sentence_len_cv=0.5,
        dialogue_ratio=0.5,
        particle_ratio=0.5,
        comma_per_sentence=0.5,
        terminal_ratio=0.5,
    )


# ---------------------------------------------------------------------------
# 1. profile —— 可测量的风格特征
# ---------------------------------------------------------------------------


def test_profile(t: T) -> None:
    from keel.audit.dress import profile

    t.group("1. profile（风格特征向量）")

    p = profile(CH_A)
    t.eq(p.mean_sentence_len, 5.5, "句长均值（[6,6,5,5] → 5.5）")
    t.eq(round(p.sentence_len_cv, 6), 0.090909, "句长变异系数")
    t.eq(p.dialogue_ratio, 0.0, "无对话 → 0")
    t.eq(round(p.particle_ratio, 6), 0.136364, "虚词占比 3/22")
    t.eq(p.comma_per_sentence, 0.0, "无逗号 → 0")
    t.eq(p.terminal_ratio, 0.0, "无叹/问号 → 0")

    # 对话与标点节奏
    t.eq(profile("「你来了」他说。天黑了。").dialogue_ratio, 0.5, "对话句占比 1/2")
    t.eq(profile("他走了！真的吗？").terminal_ratio, 1.0, "叹/问号密度 2/2")

    # 空文本 → 全零档案，不炸
    t.eq(profile("").mean_sentence_len, 0.0, "空文本 → 均值 0")
    t.eq(profile("   \n  ").particle_ratio, 0.0, "空白文本 → 虚词比 0")

    # 确定性
    t.eq(profile(CH_A), profile(CH_A), "同一文本两次 → 档案完全相同")


# ---------------------------------------------------------------------------
# 2. baseline —— 中位数基线（剔除 2σ 离群）
# ---------------------------------------------------------------------------


def test_baseline(t: T) -> None:
    from keel.audit.dress import StyleProfile, baseline

    t.group("2. baseline（剔除 2σ 离群的中位数）")

    clean = [10.0, 10.5, 11.0, 9.5, 10.2]
    outlier = 100.0  # 一章极端漂移
    ps = [_prof(v) for v in clean + [outlier]]

    b = baseline(ps)
    mean_all = statistics.mean(p.mean_sentence_len for p in ps)
    median_all = statistics.median([p.mean_sentence_len for p in ps])
    clean_median = statistics.median(clean)

    # 关键：基线等于「干净章的中位数」10.2，而**不是**全量中位数 10.35 ——
    # 后者才是「没剔除离群」时会得到的值，两者不同即证明剔除确实发生。
    t.eq(b.mean_sentence_len, 10.2, "基线 = 剔除离群后的中位数 10.2")
    t.eq(clean_median, 10.2, "干净章中位数 = 10.2")
    t.eq(median_all, 10.35, "全量中位数（未剔除）= 10.35 ≠ 10.2 → 剔除有效")
    t.eq(round(mean_all, 2), 25.2, "含离群章的均值被拖到 25.2")

    t.eq(b.sentence_len_cv, 0.5, "其余特征不受影响")
    t.ok(abs(b.mean_sentence_len - clean_median) < 1e-9, "中位数基线几乎不动")
    t.ok(mean_all - clean_median > 10, "均值被离群拖走 >10（中位数没有）")

    # 退化输入
    t.eq(baseline([]), StyleProfile(), "空列表 → 全零档案")
    t.eq(baseline([ps[0]]), ps[0], "单章 → 就是它自己")


# ---------------------------------------------------------------------------
# 3. style_fidelity —— 风格保真度
# ---------------------------------------------------------------------------


def test_style_fidelity(t: T) -> None:
    from keel.audit.dress import baseline, profile, style_fidelity

    t.group("3. style_fidelity（风格保真度）")

    pa, pb = profile(CH_A), profile(CH_B)
    t.eq(style_fidelity(pa, pa), 1.0, "同一文本 → 保真度 1.0")
    t.eq(style_fidelity(pa, pb), 1.0, "同风格异内容 → 保真度 1.0")

    base = baseline([pa, pb, profile(CH_C)])
    t.eq(style_fidelity(pa, base), 1.0, "对三章基线 → 保真度 1.0")

    drift = style_fidelity(profile(LONG_SENTENCE), profile(SHORT_SENTENCES))
    t.eq(round(drift, 4), 0.7667, "长句 vs 短句 → 保真度 0.7667")
    t.ok(drift < 1.0, "风格漂移 → 保真度下降")


# ---------------------------------------------------------------------------
# 4. content_independence —— 本模块的核心（非对称）
# ---------------------------------------------------------------------------


def test_content_independence(t: T) -> None:
    from keel.audit.dress import content_independence, profile, style_fidelity

    t.group("4. content_independence（内容独立性：非对称是全部价值）")

    ci_same = content_independence(CH_A, CH_A)
    ci_diff = content_independence(CH_A, CH_B)

    t.eq(ci_same, 0.0, "同一内容 → 独立性 0（相似性被内容解释）")
    t.eq(ci_diff, 1.0, "内容不同 → 独立性 1（相似性无法被内容解释）")
    t.ok(ci_same < 0.3, "同一内容：独立性低")
    t.ok(ci_diff > 0.7, "异内容：独立性高")
    t.ok(ci_diff - ci_same > 0.5, "非对称：两者相差 >0.5")

    # 非对称的证明：两对的风格保真度**相同**，唯一差异是独立性。
    # 所以任何「对两种情况返回同一个值」的实现都会在这里失败。
    t.eq(
        style_fidelity(profile(CH_A), profile(CH_A)),
        style_fidelity(profile(CH_A), profile(CH_B)),
        "两对的风格保真度相同（差异只可能来自独立性）",
    )

    # 空基线：没有可被内容解释的相似性 → 独立性为 1
    t.eq(content_independence(CH_A, ""), 1.0, "空基线 → 独立性 1")


# ---------------------------------------------------------------------------
# 5. fluency —— 流畅度
# ---------------------------------------------------------------------------


def test_fluency(t: T) -> None:
    from keel.audit.dress import fluency

    t.group("5. fluency（流畅度）")

    t.eq(fluency(CH_A), 1.0, "干净文本 → 1.0")
    t.eq(fluency("他走了。他走了。他走了。他走了。"), 0.625, "整段重复 → 0.625")
    t.eq(fluency(""), 0.0, "空文本 → 0.0")
    t.ok(fluency(LONG_CHAPTER) < 1.0, "超长句 → 有惩罚")


# ---------------------------------------------------------------------------
# 6. authenticity —— 三维乘积与 passed 边界
# ---------------------------------------------------------------------------


def test_authenticity(t: T) -> None:
    from keel.audit.dress import AuthenticityReport, authenticity, baseline, profile

    t.group("6. authenticity（三维乘积 + passed 边界）")

    base = baseline([profile(CH_A), profile(CH_B), profile(CH_C)])
    r = authenticity(CH_A, CH_B, base)
    t.eq(r.style_fidelity, 1.0, "dim1 style_fidelity")
    t.eq(r.content_independence, 1.0, "dim2 content_independence")
    t.eq(r.fluency, 1.0, "dim3 fluency")
    t.eq(r.overall, 1.0, "overall = 三者乘积")
    t.ok(r.passed, "overall 1.0 ≥ 1-0.15 → 通过")

    # 同一内容 → 独立性 0 → 整体 0：风格保真度再高也没用
    same = authenticity(CH_A, CH_A, profile(CH_A))
    t.eq(same.style_fidelity, 1.0, "同一内容：保真度仍是 1.0")
    t.eq(same.content_independence, 0.0, "同一内容：独立性 0")
    t.eq(same.overall, 0.0, "同一内容：整体 0")
    t.ok(not same.passed, "同一内容 → 不通过（相似性被内容解释掉了）")

    # passed 边界 = 1 - threshold（默认 0.15）
    d = 1.0 - 0.15
    t.eq(AuthenticityReport(1.0, 1.0, d).overall, d, "边界 overall")
    t.ok(AuthenticityReport(1.0, 1.0, d).passed, "overall == 1-threshold → 通过")
    t.ok(
        not AuthenticityReport(1.0, 1.0, d * 0.999).passed,
        "略低于 1-threshold → 不通过",
    )
    # 换一个二进制精确的阈值，验证边界是「≥」而不是「>」
    t.ok(AuthenticityReport(1.0, 1.0, 0.5, threshold=0.5).passed, "0.5 == 1-0.5 → 通过")
    t.ok(
        not AuthenticityReport(1.0, 1.0, 0.499, threshold=0.5).passed,
        "0.499 < 1-0.5 → 不通过",
    )


# ---------------------------------------------------------------------------
# 7. scan_ir —— 跨章风格漂移门禁
# ---------------------------------------------------------------------------


def test_scan_ir(t: T) -> None:
    from keel.audit.dress import scan_ir
    from keel.ir.enums import Severity

    t.group("7. scan_ir（跨章漂移门禁）")

    # 干净：三章同风格、异内容 → 无结论
    t.eq(scan_ir(_prose_ir([CH_A, CH_B, CH_C])), [], "同风格异内容的三章 → 无漂移")

    # 漂移：注入一章长句 → 1 条，归给那一章
    ir = _prose_ir([CH_A, CH_B, CH_C, LONG_CHAPTER])
    fs = scan_ir(ir)
    t.eq(len(fs), 1, "注入长句章 → 1 条")
    if fs:
        t.eq(fs[0].code, "audit:style_drift", "code")
        t.eq(fs[0].scene_id, "sc4", "结论归给漂移的那章")
        t.eq(fs[0].severity, Severity.WARN, "风格漂移 → WARN")
        t.ok("漂移" in fs[0].message, "消息含「漂移」")
        t.ok(fs[0].evidence.get("content_independence") is not None, "证据含三维数字")

    # 确定性
    t.eq(scan_ir(ir), scan_ir(ir), "同一输入两次 → 结果相同")

    # 数据不足 / 边界
    t.eq(scan_ir(_prose_ir([CH_A])), [], "单章 → 无法建基线 → 无结论")
    t.eq(scan_ir(_prose_ir([])), [], "无正文 → 无结论")

    # 空 prose 被跳过，剩下的三章同风格 → 无结论
    mixed = _ir(
        [
            _scene("sc1", CH_A, 0),
            _scene("sc2", None, 1),
            _scene("sc3", CH_B, 2),
            _scene("sc4", CH_C, 3),
        ]
    )
    t.eq(scan_ir(mixed), [], "空 prose 被跳过 → 三章同风格 → 无结论")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  DRESS 风格漂移三维检测 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_profile(t)
        test_baseline(t)
        test_style_fidelity(t)
        test_content_independence(t)
        test_fluency(t)
        test_authenticity(t)
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
