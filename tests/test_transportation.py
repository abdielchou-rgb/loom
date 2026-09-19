"""叙事传输度 6 维评分 —— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**，期望值全部从
传输理论、好奇心缺口理论、以及汉语语法推导，不是从实现里抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_transportation.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `tests/test_dress.py` 同风格。

── 为什么这个模块值得存在 ──────────────────────────────

「读者被故事吸进去了多少」这件事，Keel 此前完全没有度量。`anti_slop`
只惩罚「坏」（AI 味），`craft` 只惩罚「平」（张力不足），`dress` 只度量
「漂」（风格漂移）。**没有任何一项奖励「留白」** —— 而留白恰恰是拉力的来源。

── 两个结构性洞察（本模块的全部价值）────────────────────

1. **「太少未解释」也是缺陷。**
   `unexplained_count == 0` 得 **30 分**，不是满分。
   一个当场把一切都解释清楚的故事，读者没有可lean进去的开放问题。
   Loewenstein (1994) 的**信息缺口理论**：好奇心来自「已知」与「想知道」
   之间那道被明确感知到的缝；缝被立刻填平，驱力即消失。
   所以「最干净、最完整、什么都不欠」的文本**不可能是最高分** ——
   这个反转正是本模块要钉死的东西（第 4 组）。

2. **目标带（target band）而非单调指标。**
   `sentence_variety = 100 - |CV − 0.7| × 100`。
   CV ≈ 0.7 最好；**太低（句长齐平、节奏单调）与太高（长短乱跳、节奏失序）
   都要扣分**。这是「带」，不是「越多越好」（第 2 组）。
   任何「CV 越高分越高」的单调实现都在这里失败。

── 期望值的来源 ─────────────────────────────────────────

  Green & Brock (2000), "The role of transportation in the persuasiveness of
  public narratives", J. Pers. Soc. Psychol. 79(5), 701–721 —— 叙事传输
  是一个可测量的构念：注意、意象、情感的**同时**卷入。

  Loewenstein (1994), "The psychology of curiosity: A review and
  reinterpretation", Psychological Bulletin 116(1), 75–98 —— 信息缺口理论，
  即「零未解释 = 无拉力」这一反直觉结论的依据。

  （六个维度的**权重**没有任何引用来源，是设计先验，不是测量常数 ——
   见 `keel/audit/transportation.py` 的 `DEFAULT_WEIGHTS`。测试只断言
   权重之和为 1、以及各维度的**结构行为**，不断言「0.3 比 0.2 更正确」。）

── 期望值的算法来源 ─────────────────────────────────────

  句长变异系数 CV = 总体标准差 / 均值（`statistics.pstdev` / `fmean`）。
  用总体而非样本标准差：这里的「总体」就是这一段文本的全部句子，
  不是从中抽样，无需 Bessel 修正（与 `keel/audit/dress.py` 一致）。

  第 2 组的三个样本句长序列是**手工设计**的，使 CV 恰好落在带的三个位置：
      单调   lens = [3, 3, 3]        →  CV = 0.0   →  期望 30
      靶心   lens = [3, 17]          →  CV = 0.7   →  期望 100（精确）
      失序   lens = [1,1,1,1,40]     →  CV = 1.7727 →  期望 0（触底）
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

#: 单调：三句同长（lens=[3,3,3]）→ CV=0 → 目标带**低**侧。
MONOTONE = "他走了。他走了。他走了。"

#: 靶心：lens=[3,17] → mean=10, pstdev=7 → CV=0.7 **精确** → 期望 100。
ON_TARGET = "他走了。他站在那条很长很长的走廊尽头等着她。"

#: 失序：lens=[1,1,1,1,40] → mean=8.8, pstdev=15.6 → CV=1.7727 → 目标带**高**侧。
CHAOTIC = (
    "走。停。看。听。"
    "他站在那条很长很长的走廊尽头等着她的出现直到天完全黑下来也没有等到她的身影与脚步。"
)

#: 平淡：无感官、无对话、句长齐平、纯第三人称、无打断、无未解问题。
FLAT = "他走进屋子。他坐下歇息。他抬起头来。他低下头去。"

#: 健康：有对话、有感官、有打断、句长有起伏 —— 并且**挂着一个未解之谜**。
RICH = "「我走了」她说。他摸着冰凉的墙没有回答。窗外潮湿的风灌进来，屋里漆黑一片，只听见自己的心跳。"

#: 自证：表面上很健康（对话 50%、打断密集、有感官），但**没有任何未解问题**。
#: 它用来证明「零未解释」的惩罚**不是**「总分低」的代理 —— 它单独就能触发。
SELF_EXPLAINED = "「我走了」——她说。他摸着冰凉的墙——没有回答。"

#: 六维混合样本，用于精确断言各维数值。
MIX = "「你为什么要走」她问。他摸着冰凉的墙，没有回答。窗外下着雨，很冷。"


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


def _enigma(eid: str, scene_id: str, state=None):
    """挂一条谜题台账（默认 POSED —— 未解）。"""
    from keel.ir.enums import EnigmaState
    from keel.ir.models import Enigma

    kw = {"state": EnigmaState.POSED} if state is None else {"state": state}
    return Enigma(id=eid, question="他为什么走", planted_at_scene=scene_id, **kw)


def _ir(scenes, enigmas=()):
    from keel.ir.enums import ArcShape
    from keel.ir.models import CommitmentLayer, NarrativeIR

    return NarrativeIR(
        title="传输度测试",
        commitment=CommitmentLayer(
            premise="贪念必然反噬",
            controlling_idea="想留住的人，最后都是自己推走的",
            logline="刀客收尸时认出自己的名字",
            arc_shape=ArcShape.MAN_IN_A_HOLE,
            ending_anchor="他把刀留在雪地里",
        ),
        scenes=scenes,
        enigmas=list(enigmas),
    )


# ---------------------------------------------------------------------------
# 1. 感官 / 对话 / 打断 —— 三个「密度型」维度
# ---------------------------------------------------------------------------


def test_density_dims(t: T) -> None:
    from keel.audit.transportation import (
        dialogue_score,
        interruption_score,
        sensory_score,
    )

    t.group("1. 密度型三维（感官 / 对话 / 打断）")

    # 感官：命中密度 / 句，靶 1.0 命中/句
    t.eq(sensory_score("他走进屋子。他坐下。"), 0.0, "无感官词 → 0")
    t.eq(sensory_score("他摸着冰凉的墙。风吹进来很潮湿。"), 100.0, "2 句 2 命中 → 100")
    t.eq(sensory_score("他摸着冰凉的墙。他坐下。"), 50.0, "2 句 1 命中 → 50")
    t.ok(
        sensory_score("屋里漆黑一片。雾气弥漫。") > 0.0,
        "视觉通道也算感官细节（不只有触觉）",
    )

    # 对话：含对话标记的句子占比 / 靶 0.5
    t.eq(dialogue_score("他走了。她笑了。"), 0.0, "无对话标记 → 0")
    t.eq(dialogue_score("「你来了」他说。天黑了。"), 100.0, "1/2 句有对话 → 100")
    t.eq(
        dialogue_score("「你来了」他说。天黑了。他走了。雨停了。"),
        50.0,
        "1/4 句有对话 → 50",
    )

    # 打断：破折号 / 省略号的密度 / 靶 0.5
    t.eq(interruption_score("他走了。她笑了。"), 0.0, "无打断标记 → 0")
    t.eq(interruption_score("我——我没说。他笑了。"), 100.0, "2 句 1 个破折号 → 100")
    t.eq(
        interruption_score("我——我没说。他笑了。天黑了。雨停了。"),
        50.0,
        "4 句 1 个破折号 → 50",
    )
    t.eq(interruption_score("他张了张嘴……没说。她笑了。"), 100.0, "省略号也算打断")

    # 空文本 → 0，不炸
    t.eq(sensory_score(""), 0.0, "空文本 → 感官 0")
    t.eq(dialogue_score("   "), 0.0, "空白文本 → 对话 0")
    t.eq(interruption_score(""), 0.0, "空文本 → 打断 0")


# ---------------------------------------------------------------------------
# 2. 句长变异 —— 目标带（双侧！）
# ---------------------------------------------------------------------------


def test_sentence_variety_band(t: T) -> None:
    from keel.audit.transportation import sentence_variety_score as V

    t.group("2. 句长变异 —— 目标带（本模块的结构性洞察之二）")

    # 三个位置：带下方 / 靶心 / 带上方
    t.eq(V(MONOTONE), 30.0, "CV=0（句长齐平）→ 30（**低**）")
    t.eq(V(ON_TARGET), 100.0, "CV=0.7（精确靶心）→ 100（**高**）")
    t.eq(V(CHAOTIC), 0.0, "CV=1.7727（长短乱跳）→ 0（**低**）")

    # 先用 statistics 独立复算，证明上面的样本确实落在带的三个位置
    lens = [len(s) for s in CHAOTIC.split("。") if s.strip()]
    cv = statistics.pstdev(lens) / statistics.fmean(lens)
    t.eq(lens, [1, 1, 1, 1, 40], "失序样本句长序列")
    t.eq(round(cv, 4), 1.7727, "失序样本 CV = 1.7727（> 0.7）")

    lens_at = [len(s) for s in ON_TARGET.split("。") if s.strip()]
    cv_at = statistics.pstdev(lens_at) / statistics.fmean(lens_at)
    t.eq(lens_at, [3, 17], "靶心样本句长序列")
    t.eq(round(cv_at, 10), 0.7, "靶心样本 CV = 0.7（精确）")

    # 双侧性：靶心必须同时高于两侧
    t.ok(V(ON_TARGET) > V(MONOTONE), "靶心 > 单调（低侧扣分）")
    t.ok(V(ON_TARGET) > V(CHAOTIC), "靶心 > 失序（高侧也扣分）")
    t.ok(V(MONOTONE) != V(CHAOTIC), "两侧不必相等，但都低于靶心")
    # 这一条专门钉死单调实现：CV 越高 ≠ 分越高
    t.ok(V(CHAOTIC) < V(ON_TARGET), "高 CV **不得**高于靶心 —— 单调实现在此失败")

    # 边界：单句 → CV=0 → 30；空 → 0
    t.eq(V("他走了。"), 30.0, "单句 → CV=0 → 30")
    t.eq(V(""), 0.0, "空文本 → 0")


# ---------------------------------------------------------------------------
# 3. 视角一致性 —— 人称混用（对话豁免）
# ---------------------------------------------------------------------------


def test_pov(t: T) -> None:
    from keel.audit.transportation import pov_consistency_score as P

    t.group("3. 视角一致性（第一/第三人称混用；对话豁免）")

    t.eq(P("他来了。她走了。"), 100.0, "纯第三人称 → 100")
    t.eq(P("我来了。我走了。"), 100.0, "纯第一人称 → 100")
    t.eq(P("天黑了。雨停了。"), 100.0, "无人称代词 → 100（无可测的混用）")
    t.eq(P("我来了。他说天黑了。"), 0.0, "1:1 混用 → 0（最差）")

    # 1:3 → mixing = 1/3 = 0.3333；容差 0.1
    #   → 100 × (1 − (0.3333−0.1)/0.9) = 74.0741
    # 注意：第一人称 1 个、第三人称**必须 3 个**（他/她/它），才是 1:3。
    t.eq(
        round(P("我来了。他说天黑了。她笑了。它响了。"), 4),
        74.0741,
        "1:3 混用 → 74.0741（偏离平衡越远，扣得越少）",
    )

    # 关键：对话里的「我」不算视角混用 —— 否则两人正常对话全部误报
    t.eq(P("「我来了」他说。天黑了。"), 100.0, "对话内的第一人称被豁免")
    t.eq(
        P("「我走了」她说。他摸着墙没有回答。"),
        100.0,
        "第三人称叙述 + 第一人称对白 → 仍是 100",
    )

    t.eq(P(""), 0.0, "空文本 → 0")


# ---------------------------------------------------------------------------
# 4. 未解释密度 —— 零惩罚（本模块的结构性洞察之一）
# ---------------------------------------------------------------------------


def test_unexplained(t: T) -> None:
    from keel.audit.transportation import count_open_questions as C
    from keel.audit.transportation import unexplained_score as U

    t.group("4. 未解释密度 —— 「太少未解释」也是缺陷")

    t.eq(U(0), 30.0, "0 个未解问题 → 30（**不是满分**）")
    t.eq(U(1), 100.0, "1 个 → 100（目标带）")
    t.eq(U(2), 100.0, "2 个 → 100（目标带）")
    t.eq(U(3), 100.0, "3 个 → 100（目标带上沿）")
    t.eq(U(4), 90.0, "4 个 → 90（开始过剩）")
    t.eq(U(5), 80.0, "5 个 → 80")
    t.eq(U(13), 20.0, "13 个 → 20（地板）")

    t.ok(U(0) < U(2), "零未解释 **低于** 少量未解释 —— 反直觉正是本模块的价值")
    t.ok(U(0) < U(5), "零未解释也低于「过剩」—— 它是带外的低点，不是最优点")

    # 文本侧的降级代理：只认**疑问构式**，不数「？」的个数
    # （源项目 `open_questions` 只数问号，Keel 不抄那个 —— 这一条把它钉死）
    t.eq(C("他为什么要走。"), 1, "「为什么」→ 1")
    t.eq(C("究竟是谁。为什么。"), 2, "两个疑问位置 → 2")
    t.eq(
        C("究竟是谁。"),
        1,
        "同一处疑问里的两个构式合并为 1（否则悬念被凭空翻倍）",
    )
    t.eq(C("他走进屋子。他坐下。"), 0, "陈述句 → 0")
    t.eq(C("他走了？"), 0, "**裸问号不计** —— 我们识别的是疑问构式，不是问号")
    t.eq(C(""), 0, "空文本 → 0")


# ---------------------------------------------------------------------------
# 5. score —— 加权合成、空文本、确定性、以及「反转」
# ---------------------------------------------------------------------------


def test_score(t: T) -> None:
    from keel.audit.transportation import (
        DEFAULT_WEIGHTS,
        TransportationScore,
        score,
    )

    t.group("5. score（加权合成 + 反转）")

    # 权重是**先验**：只断言结构性质，不断言「0.3 比 0.2 更正确」
    t.eq(round(sum(DEFAULT_WEIGHTS.values()), 10), 1.0, "权重之和 = 1")
    t.eq(
        set(DEFAULT_WEIGHTS),
        {"sensory", "dialogue", "sentence_variety", "pov_consistency",
         "unexplained", "interruption"},
        "权重键与六个维度一一对应",
    )

    # 精确数值：MIX 六维全部可手算
    r = score(MIX, open_questions=2)
    t.eq(round(r.sensory, 4), 33.3333, "感官：3 句 1 命中 → 33.3333")
    t.eq(round(r.dialogue, 4), 66.6667, "对话：1/3 句 → 66.6667")
    t.eq(round(r.sentence_variety, 4), 46.3299, "句长变异：CV=0.1633 → 46.3299")
    t.eq(r.pov_consistency, 100.0, "视角：纯第三人称 → 100")
    t.eq(r.unexplained, 100.0, "未解释：2 个 → 100")
    t.eq(r.interruption, 0.0, "打断：无 → 0")
    t.eq(round(r.overall, 4), 55.2828, "加权总分 55.2828")

    # 空文本 / 空白文本 → 全零（不是「完美」，是「没测」）
    zero = TransportationScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    t.eq(score(""), zero, "空文本 → 六维全零")
    t.eq(score("   \n  "), zero, "空白文本 → 六维全零")
    t.eq(score("").overall, 0.0, "空文本总分 0")

    # 确定性
    t.eq(score(MIX, open_questions=2), score(MIX, open_questions=2), "同一输入两次 → 相同")

    # ── 反转：同一文本，未解问题 0 个 vs 2 个 ────────────────────
    a = score(MIX, open_questions=0)
    b = score(MIX, open_questions=2)
    t.eq(a.unexplained, 30.0, "无未解问题 → 该维 30")
    t.eq(b.unexplained, 100.0, "2 个未解问题 → 该维 100")
    t.ok(a.overall < b.overall, "**同一文本**：无未解问题反而总分更低")
    t.eq(
        round(b.overall - a.overall, 6),
        7.0,
        "差值恰为 0.1 × (100 − 30) = 7 —— 差异只来自「未解释」这一维",
    )

    # ── 「最干净的可能文本」不可能是最高分 ──────────────────────
    clean = score(FLAT, open_questions=0)
    t.ok(clean.overall < 100.0, "全解释清楚 → 总分 < 100")
    t.ok(
        clean.overall <= 93.0,
        "未解释 = 30 时总分上限 = 0.9×100 + 0.1×30 = 93 —— 结构性的天花板",
    )


# ---------------------------------------------------------------------------
# 6. scan_ir —— 用 Enigma 台账（不是数问号）
# ---------------------------------------------------------------------------


def test_scan_ir(t: T) -> None:
    from keel.audit.transportation import scan_ir
    from keel.ir.enums import EnigmaState, Severity

    t.group("6. scan_ir（IR 门禁；未解问题取自 Enigma 台账）")

    # 健康：有对话/感官/打断 + 挂着一个未解之谜 → 无结论
    healthy = _ir([_scene("sc1", RICH, 0)], [_enigma("en1", "sc1")])
    t.eq(scan_ir(healthy), [], "健康场次 + 未解之谜 → 无结论")

    # 平淡：无未解之谜、六维全面偏低 → 两条结论
    flat_ir = _ir([_scene("sc1", FLAT, 0)])
    fs = scan_ir(flat_ir)
    t.eq(
        sorted(f.code for f in fs),
        ["audit:over_explained", "audit:transportation"],
        "平淡场次 → 零未解释 + 传输度偏低",
    )
    codes = {f.code: f for f in fs}
    t.eq(codes["audit:over_explained"].scene_id, "sc1", "结论归给该场次")
    t.eq(codes["audit:over_explained"].severity, Severity.WARN, "零未解释 → WARN")
    t.eq(codes["audit:over_explained"].evidence["open_questions"], 0, "证据：未解问题数")
    t.eq(codes["audit:transportation"].severity, Severity.WARN, "传输度偏低 → WARN")
    t.ok(
        "transportation" in codes["audit:transportation"].evidence
        or codes["audit:transportation"].evidence.get("overall") is not None,
        "传输度结论带 overall 证据",
    )

    # 自证：表面健康（对话 50%、打断密集、有感官），但没有未解问题
    # —— 证明「零未解释」的惩罚**单独**就能触发，不是低总分的代理
    self_ir = _ir([_scene("sc1", SELF_EXPLAINED, 0)])
    sfs = scan_ir(self_ir)
    t.eq(
        [f.code for f in sfs],
        ["audit:over_explained"],
        "表面健康但零未解释 → **只有**这一条（总分并未偏低）",
    )

    # 同一文本挂上一条未解之谜 → 结论消失（证明台账真的在承重）
    fixed = _ir([_scene("sc1", SELF_EXPLAINED, 0)], [_enigma("en1", "sc1")])
    t.eq(scan_ir(fixed), [], "同一文本 + 一条未解之谜 → 结论消失")

    # 已解之谜不算未解
    resolved = _ir(
        [_scene("sc1", SELF_EXPLAINED, 0)],
        [_enigma("en1", "sc1", state=EnigmaState.RESOLVED)],
    )
    t.ok(
        any(f.code == "audit:over_explained" for f in scan_ir(resolved)),
        "RESOLVED 的谜题不算未解问题",
    )

    # 确定性
    t.eq(scan_ir(flat_ir), scan_ir(flat_ir), "同一输入两次 → 结果相同")

    # 数据不足
    t.eq(scan_ir(_ir([])), [], "无场景 → 无结论")
    t.eq(scan_ir(_ir([_scene("sc1", None, 0)])), [], "无正文 → 无结论")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  叙事传输度 6 维评分 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_density_dims(t)
        test_sentence_variety_band(t)
        test_pov(t)
        test_unexplained(t)
        test_score(t)
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
