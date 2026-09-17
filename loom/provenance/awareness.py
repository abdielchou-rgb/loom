"""写作过程中的「觉察」回显 —— 把已有数据换个出口。

── 来源（本模块存在的理由）────────────────────────────────────
Bhat, Aubin Le Quéré, Naaman, Jakesch ——
*Reactive Writers: How Co-Writing with AI Changes How We Engage with Ideas*,
**CHI 2026**（arXiv:2603.10374）。

  混合方法：19 人回溯式访谈 + 对 **1,291 次** AI 协同写作会话的量化追踪。
  三个发现，逐条对应到工程：

  1. 与 AI 建议打交道（阅读 + 决定接受/拒绝）**取代了**构思与语言生成，
     成为写作的**中心活动**。
  2. 作者常常**没有先完成自己的构思**，于是 AI 建议的想法为后续方向**下了种子**，
     作者再去铺陈这些方向。
  3. **作者没有察觉 AI 的影响，并且感觉完全掌控着自己的写作** ——
     因为在原则上，他们随时可以编辑最终文本。

  该研究把这个模式命名为 **Reactive Writing**：「一种评估优先、建议主导的写作实践，
  它显著区别于 AI 辅助下的传统写作，并且极易受到 AI 诱导的偏见与观点漂移的影响。」

── 由此得到的两条工程结论 ─────────────────────────────────────

**1. 留痕如果不能发生在「写作过程中」，对 Reactive Writing 就没有纠正作用。**

`process.py` 的 `CreativeProcessReport` **已经**把判断存下来了，
但那是**申诉时**才导出的材料。一个在写完三天后才看到「你拒绝了 7 次」的作者，
**他的写作过程并没有被改变** —— 论文说的缺失物是**过程中的觉察**，
不是**事后可举的证据**。

本模块不生产新数据，只把同一份数据**换个出口**：在每一次交互里回显。
这不是新功能，是已有能力的重新定位（第一性原理执行原则 2）。

**2. 判据必须是「作者做了多少判断」，不是「AI 生成了多少字」。**

后者会**鼓励** Reactive Writing（读建议 → 挑一个 → 计数字数），
前者让作者看见自己的能动性 —— 这正是论文说作者**看不见**的东西。

── 数据来源 ───────────────────────────────────────────────────
一律取 `ir.proposals`（已持久化），**不取内存态遥测**（`DecisionTelemetry`）。
理由与 `process.py` 一致：觉察必须**跨会话**成立 ——
作者第二天回来接着写，内存里的遥测早没了，而 IR 还在。

── 刻意不做的事 ───────────────────────────────────────────────
* **不评分、不评级。** 「你的判断力 72 分」是把觉察又变成了一个可刷的指标，
  那恰恰会诱导 Reactive Writing。只报数，不评判。
* **不预测、不建议。** 只呈现作者已经做了什么，不告诉他应该做什么。
* **不阻断。** 判断数为 0 时不报错，只提示 —— Loom 不强制作者先构思。
"""

from __future__ import annotations

from ..ir.enums import ChunkOrigin
from ..ir.models import NarrativeIR
from ..ir.proposal import DiffStatus

__all__ = [
    "counts",
    "awareness_line",
    "awareness_block",
    "scenes_touched",
]

#: 判断数从 0 到「作者确实在做决定」的经验分界。
#: 刻意不设成硬阈值 —— 见模块 docstring「刻意不做的事」。
#: 这个数只用于措辞（"尚无判断" vs "已做 N 次判断"），不用于任何门禁。
_SIGNIFICANT = 1


def counts(ir: NarrativeIR) -> dict[str, int]:
    """统计 IR 里的裁决分布。**只看持久化状态**，不看内存遥测。

    返回键：`decided` / `accepted` / `rejected` / `conflicted` / `pending` / `total`。
    `decided = accepted + rejected + conflicted`（三种都已裁决），
    `total = decided + pending`。
    """
    out = {
        "accepted": 0,
        "rejected": 0,
        "conflicted": 0,
        "pending": 0,
    }
    for d in ir.proposals:
        if d.status is DiffStatus.ACCEPTED:
            out["accepted"] += 1
        elif d.status is DiffStatus.REJECTED:
            out["rejected"] += 1
        elif d.status is DiffStatus.CONFLICTED:
            out["conflicted"] += 1
        elif d.status is DiffStatus.PENDING:
            out["pending"] += 1
    out["decided"] = out["accepted"] + out["rejected"] + out["conflicted"]
    out["total"] = out["decided"] + out["pending"]
    return out


#: 人工做过功的来源。注意 `AI_EDITED` 是「AI 生成 + 人工修改」——
#: 它**也算**人动了手，而且恰恰是最该被看见的一类：
#: 作者不只是批准或驳回，而是真的改了内容。
#: 排除的只有 `AI_GENERATED`（人没碰）与 `IMPORTED`（不是本轮产生的）。
_HUMAN_WORK = frozenset(
    {ChunkOrigin.HUMAN, ChunkOrigin.AI_ASSISTED, ChunkOrigin.AI_EDITED}
)


def scenes_touched(ir: NarrativeIR) -> int:
    """有多少个场景**人工做过功**。

    与「做了多少次裁决」互补：裁决是**判断**（接受/拒绝/标冲突），
    这个是**动手**（真的改了内容）。两者合起来才说得清「人参与了什么」。
    """
    return sum(1 for s in ir.scenes if s.origin in _HUMAN_WORK)


def awareness_line(ir: NarrativeIR) -> str:
    """一行觉察回显。这是本模块的主出口，设计成可以直接塞进任何日志。

    刻意**只报数、不评判**：数字本身就在告诉作者「AI 提了多少、你定了多少」，
    再加一句评价反而会把觉察变成又一个指标。
    """
    c = counts(ir)
    if c["total"] == 0:
        return "本次尚无结构提案 —— 没有需要你裁决的东西"

    parts: list[str] = []
    if c["decided"]:
        seg = f"已做判断 {c['decided']} 次"
        split = [f"采纳 {c['accepted']}", f"驳回 {c['rejected']}"]
        if c["conflicted"]:
            split.append(f"标冲突 {c['conflicted']}")
        parts.append(seg + "（" + " / ".join(split) + "）")
    else:
        parts.append("尚**未**做出判断")

    if c["pending"]:
        parts.append(f"待你裁决 {c['pending']} 条")

    touched = scenes_touched(ir)
    if touched:
        parts.append(f"人工改写场景 {touched} 个")

    return " · ".join(parts)


def awareness_block(ir: NarrativeIR) -> list[str]:
    """多行觉察区块，给 CLI 与 HTML 报告用。

    第一行是 `awareness_line`；后面补一句**为什么给这个数** ——
    不解释的话，作者只会把它当成又一个统计噪声。
    """
    c = counts(ir)
    lines = [awareness_line(ir)]
    if c["total"] == 0:
        return lines

    lines.append(
        "  ↑ CHI 2026：AI 协同写作中，作者往往**察觉不到** AI 对自己方向的影响，"
    )
    lines.append(
        "    却感觉完全掌控。这一行让「你做了多少判断」在写作时可见，而不是申诉时才导出。"
    )
    if c["decided"] == 0 and c["pending"] > 0:
        lines.append(
            f"  ⚠ 有 {c['pending']} 条 AI 提案还等着你裁决 —— 未裁决的东西不构成你的判断。"
        )
    return lines
