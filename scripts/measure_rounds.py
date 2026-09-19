#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`max_rounds` 实测 —— 用「会真改写的 reviser」注入，测**循环机制**。

── 为什么要这个脚本 ─────────────────────────────────────────────
`CriticLoop` 的 `max_rounds` 默认值一直是 2，但**从来没人测过**。
PLOTTER（ACL 2026 Findings）实测图规划是 **K=3 峰值、K=5 退化**，
Keel 走的是同一条迭代路线，所以这个默认值不该是拍脑袋的。

之前测不出结论，是因为 `MockGenerator` 的 `revise` 返回
`{'prose': <原样>, 'changed': False}` —— 它是**设计上就不改写**的
确定性桩件（用于回归测试，不是用于模拟 LLM）。

── 解法与它的边界 ───────────────────────────────────────────────
注入一个**真会改写**的 reviser，从而测出**循环机制**：

  ✅ 能测：收敛需要几轮、边际收益递减、调用成本（轮数 × 场景数）
  ❌ **不能测**：迭代是否导致**质量退化**

第二条尤其重要。PLOTTER 观察到的 K=5 退化来自**真实 LLM 的行为**
（过度编辑 → 文本同质化）。用脚本模拟一个「退化」出来，
等于**编造数据** —— 那比没有数据更糟。

所以本脚本只报机制指标，并在结论里明确写出「质量退化必须接真 LLM 才能测」。

运行：`.venv/Scripts/python.exe scripts/measure_rounds.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keel.audit.anti_slop import scan_slop
from keel.ir.enums import Medium
from keel.pipeline.engines import CriticLoop
from keel.validators import run_all

# （坏写法 → 好写法）。reviser 每次调用只改**一处**，
# 模拟「LLM 一轮只修一个主要问题」这个**保守**假设。
_FIXES = [
    ("这不仅仅是失去，而是更深的痛。", "他把她的名字从名单上划掉。"),
    ("他感到非常悲伤，她觉得十分愤怒。", "他握紧拳头，她别过脸去。"),
    ("In today's fast-paced world, it is important to note that.", "事情起了变化。"),
    ("总而言之，这就是人生。", "他推开门，走进夜色里。"),
    ("时间会治愈一切伤痛。", "伤口还在疼。"),
]


class RewritingReviser:
    """会真改写的测试用 reviser —— 每次调用修掉一处 slop。

    刻意**不模拟**质量退化：那需要真实 LLM，
    模拟出来的数字等于编造（见模块 docstring）。
    """

    model_id = "test/rewriting-reviser"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, task: str, payload: dict) -> dict:
        self.calls += 1
        prose = str(payload.get("prose", ""))
        for bad, good in _FIXES:
            if bad in prose:
                return {"prose": prose.replace(bad, good, 1), "changed": True}
        return {"prose": prose, "changed": False}


def _distinct2(text: str) -> float:
    bg = [text[i : i + 2] for i in range(len(text) - 1)]
    return len(set(bg)) / len(bg) if bg else 0.0


#: 起始稿子。两个约束必须同时满足，否则测不出东西：
#:   1. slop 得分必须 **< 65**（阈值），否则循环体认为「不用改」，0 次调用；
#:   2. 待修处数必须 **≤ 轮数上限**，否则测出来的「不收敛」只是
#:      「我构造的输入修不完」，不是循环的性质。
#: 实测：两处各重复一次 → 得分 0、待修 4 处，6 轮内可收敛。
#: （顺带记录一个观察：`scan_slop` 的得分在阈值附近是**断崖**的 ——
#:   一处重复一次得 86，重复两次直接掉到 0，中间没有过渡。
#:   这本身可能是个值得看的评分函数问题，但不属于本脚本的范围。）
_SLOPPY = (_FIXES[0][0] + _FIXES[1][0]) * 2


def _make_ir():
    from tests.fixtures import clean_copy

    ir = clean_copy(Medium.NOVEL)
    for s in ir.ordered_scenes():
        s.prose = _SLOPPY
    return ir


def main() -> int:
    print("=" * 72)
    print("max_rounds 实测（注入会真改写的 reviser）")
    print("=" * 72)
    print(f"起始 slop 得分：{scan_slop(_SLOPPY).score}（阈值 65，越低越脏）")
    print(f"场景数：{len(_make_ir().ordered_scenes())}")
    print()
    print(f"{'轮数':>4} {'健康分':>6} {'残留slop命中':>12} {'distinct2':>9} "
          f"{'reviser调用':>10} {'收敛于':>7}")

    rows = []
    for r in range(1, 7):
        ir = _make_ir()
        rev = RewritingReviser()
        _, log = CriticLoop(rev, max_rounds=r).run(ir)

        rep = run_all(ir)
        prose = "".join(s.prose or "" for s in ir.scenes)
        # 收敛轮数 = 日志里最后一次出现「待去 AI 味」的轮次
        conv = 0
        for line in log:
            if line.startswith("第 "):
                conv = int(line.split()[1].rstrip("轮："))
            if "待去 AI 味" in line:
                conv = 0  # 还没收敛
        # 报**残留命中数**而不是 slop 得分：得分会被截断在 0，
        # 修掉一半时得分仍是 0，看不出进展。
        hits = sum(h.count for h in scan_slop(prose).hits)
        rows.append((r, rep.score(), hits, _distinct2(prose), rev.calls, conv))
        print(f"{r:>4} {rep.score():>6} {hits:>12} "
              f"{_distinct2(prose):>9.3f} {rev.calls:>10} "
              f"{(str(conv) if conv else '未收敛'):>7}")

    print()
    print("── 结论（只看机制，不看质量）──")

    hits_by_round = [(r[0], r[2]) for r in rows]
    first_clean = next((rnd for rnd, h in hits_by_round if h == 0), None)
    base_hits = hits_by_round[0][1]

    if first_clean:
        wasted = [(rnd, calls) for rnd, _, _, _, calls, _ in rows if rnd > first_clean]
        print(f"  · 残留 slop 在 **第 {first_clean} 轮归零**（起始 {base_hits} 处）。")
        if wasted:
            print(f"  · 之后的轮次**零收益但仍有成本**："
                  f"第 {wasted[0][0]}–{wasted[-1][0]} 轮各多花 "
                  f"{wasted[0][1] - rows[first_clean - 1][4]} 次 reviser 调用。")
        print(f"  · 边际收益曲线：{base_hits} → "
              f"{' → '.join(str(h) for _, h in hits_by_round)}")
    else:
        print(f"  · 6 轮内未收敛（起始 {base_hits} 处）—— "
              f"需要更多轮或输入本身修不完。")

    print(f"  · 健康分在各轮上为 {sorted({r[1] for r in rows})} —— 与轮数无关，"
          f"因为结构分本来就不看文风（文风走 advisory 通道）。")
    print()
    print("  ⚠ 本测量**只覆盖循环机制**（收敛性 / 边际收益 / 成本）。")
    print("    **不覆盖**生成质量：PLOTTER 观察到的 K=5 退化来自真实 LLM 的")
    print("    过度编辑，用桩件模拟出来等于**编造数据**。")
    print("    → 因此本次**不改** max_rounds（仍为 2）。")
    print("    → 若要改，需要接真 LLM 重测质量维度；机制维度已给出上界参考。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
