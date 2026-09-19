"""三个平台合规向检测器的**注册层**。

┌ 为什么单独一个文件（而不是塞进 `consistency.py`）────────────────────┐
│ 这三个校验器的判据来源与其余 29 个**不同源**：                        │
│   其余来自文学方法论（McKee / Todorov / Barthes / Greimas / 李渔 …）  │
│   这三个来自**平台公开的风控口径**（番茄的 ±5% 章节字数、             │
│   一段 >4 次高频副词、一问一答工整无打断）。                          │
│ 来源不同 → 失效方式不同：方法论不会变，平台的口径会变。              │
│ 平台改口径时应当只改这一个文件 + `keel/audit/rhythm.py`，            │
│ 而不需要在文学校验器里翻找哪几条是「合规向」的。                     │
└──────────────────────────────────────────────────────────────────────┘

**本文件只有薄包装，没有算法。** 计算全在 `keel/audit/rhythm.py`
（零依赖、可单测、可被 `rhythm.scan_ir` 单独调用）。
这个分工沿用 `numeric_fact_consistency` 包装 `keel/audit/csn.py` 的先例：
原语归 `audit/`，注册归 `validators/`。

── 三个都是报表项 + advisory 通道 ───────────────────────────

它们**只产出 INFO**，注册在 `base.REPORTS` 与 `base.ADVISORY` 两个名单里：

  * `REPORTS`  → 不可能是门禁（源码里没有 WARN/ERROR，`verify.py` 扫源码断言）
  * `ADVISORY` → Finding 走 `Report.advisory`，**不进健康分**

为什么必须两个都进：`ADVISORY ⊆ REPORTS` 是被断言的（一条会报警的检查
若走 advisory，报警会被静默吞掉 = 把门禁偷偷变成装饰）。

为什么不当门禁（两条，都是实测推出来的，不是口味）：
  1. 它们不是结构缺陷 —— `score()` 是「**结构**健康分」。混进去的结果是
     装一个新检测器，分数无声下降，读者分不清「故事变差了」还是
     「多装了一个检查」。
  2. 假阳性代价不对称 —— 人类作者也写等长段落、也用「极其」。
     能产出 WARN 就会诱导作者为迁就统计画像去改写本来没问题的文字，
     那是「为检测器写作」，比 AI 味本身更糟。

── 红线（与 `keel/audit/rhythm.py` 一致，此处再写一次是因为这是入口）──

**这三个检测器用来告诉作者「平台会怎么看」，不用来帮作者骗过平台。**
不提供降 AI 率的一键改写、不提供按阈值反向优化的洗稿建议、阈值与词表
全部公开在源码里。三条理由：技术上打不赢（公开的一方永远滞后一步）、
道德上站不住（规避标识义务）、商业上致命（被认定为规避工具的连带责任
远大于功能收益）。
"""

from __future__ import annotations

from ..audit.rhythm import (
    adverb_findings,
    burstiness_findings,
    dialogue_rhythm_findings,
    scan_adverbs,
    scan_burstiness,
    scan_dialogue_rhythm,
)
from ..ir.models import NarrativeIR
from .base import Finding, register


@register("length_burstiness")
def length_burstiness(ir: NarrativeIR) -> list[Finding]:
    """长度分布的爆发度 —— 句长（微观）与场长（宏观）两个尺度。

    出处：Goh & Barabási, *Burstiness and memory in complex systems*,
    EPL 81, 48002 (2008)，B = (σ − μ) / (σ + μ)；平台侧的口径是番茄把
    「章节字数高度均等（±5%）」列为 AI 可疑信号。

    **为什么跨场算**：`anti_slop` 的 `slop:rhythm` 逐场算句长 CV，
    而平台的「章节字数均等」判的是整本书的**章节分布** ——
    逐场检测器在结构上就看不见它。单场 CV 高不代表整本分布不均匀。
    """
    texts = [s.prose for s in ir.ordered_scenes() if s.prose]
    if not texts:
        return []
    return burstiness_findings(scan_burstiness(texts))


@register("adverb_density")
def adverb_density(ir: NarrativeIR) -> list[Finding]:
    """一段话里高频副词是否超过 4 次 —— 番茄公开的 AI 可疑口径。

    判据是**密度**不是**出现**：一个「极其」不是问题，五个才是。
    阈值 4 是平台的数字，不是我们调的（抄它的口径，作者看到的结论
    才与平台一致）。
    """
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.prose:
            continue
        out.extend(adverb_findings(scan_adverbs(s.prose, scene_id=s.id)))
    return out


@register("dialogue_rhythm")
def dialogue_rhythm(ir: NarrativeIR) -> list[Finding]:
    """对话是否「一问一答工整无打断」—— 番茄公开的对话模式异常口径。

    判据：连续 ≥4 轮对话之间没有任何叙述间隔 **且** 全篇无打断标记。
    两个条件缺一不可 —— 有打断标记却仍连续裸跑，说明作者**写了**打断，
    那种不是模板。

    局限（写在文案里，不藏在代码里）：`interruption_count == 0` 只说明
    没有打断**标记词**，不说明没有被打断 —— 写成动作的打断
    （「她抬手止住他」）认不出。
    """
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.prose:
            continue
        out.extend(
            dialogue_rhythm_findings(scan_dialogue_rhythm(s.prose, scene_id=s.id))
        )
    return out


__all__ = ["adverb_density", "dialogue_rhythm", "length_burstiness"]
