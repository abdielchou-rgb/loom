"""端到端验证：一句话想法 -> 正文 -> 体检 -> 观众模拟 -> 多路渲染。

跑法：
    .venv/Scripts/python.exe scripts/pipeline_demo.py
    .venv/Scripts/python.exe scripts/pipeline_demo.py "你的想法"

不需要 API key —— 默认走离线的确定性参考生成器，
所以这个脚本同时是**回归测试基线**：同样的输入必然得到同样的输出。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.audience import (  # noqa: E402
    AudienceSimulator,
    BINGE_WEB_NOVEL,
    scene_signals,
)
from loom.audit.anti_slop import scan_ir  # noqa: E402
from loom.ir.enums import ArcShape, Medium  # noqa: E402
from loom.llm import MockGenerator, TokenLedger  # noqa: E402
from loom.pipeline import LoomPipeline  # noqa: E402
from loom.provenance.meter import ProvenanceLedger  # noqa: E402
from loom.render import (  # noqa: E402
    render_fountain,
    render_ink,
    render_renpy,
    render_storyboard,
    render_text,
)
from loom.render.text import render_outline  # noqa: E402
from loom.validators import run_all  # noqa: E402

IDEA = (
    "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字"
)
OUT = ROOT / "out" / "pipeline"


def head(n: int, title: str) -> None:
    print()
    print("═" * 64)
    print(f"  {n}. {title}")
    print("═" * 64)


def main() -> int:
    idea = sys.argv[1] if len(sys.argv) > 1 else IDEA
    OUT.mkdir(parents=True, exist_ok=True)

    ledger = TokenLedger()
    gen = MockGenerator(ledger=ledger)

    # ---------------------------------------------------------------- 1
    head(1, "想法 -> Narrative IR（六阶段流水线）")
    print(f"想法：{idea}")
    print()
    pipe = LoomPipeline(gen, ledger=ledger, on_step=lambda m: print(f"  · {m}"))
    res = pipe.run(
        idea,
        medium=Medium.NOVEL,
        arc_shape=ArcShape.MAN_IN_A_HOLE,
        template_id="save_the_cat",
        scene_count=6,
        words_per_scene=600,
    )
    ir = res.ir

    # ---------------------------------------------------------------- 2
    head(2, "IR 结构概览")
    print(f"标题        {ir.title}")
    print(f"媒介/弧光   {ir.medium.value} / {ir.commitment.arc_shape.value}")
    print(f"前提        {ir.commitment.premise}")
    print(f"控制理念    {ir.commitment.controlling_idea}")
    print(f"结局锚点    {ir.commitment.ending_anchor}")
    print(f"IR 指纹     {ir.fingerprint()}  schema {ir.schema_version}")
    print()
    print("三层正交：")
    print(f"  L1 情节层    事件 {len(ir.plot.events)}  因果链 {len(ir.plot.links)}"
          f"  孤立事件 {ir.plot.orphans() or '无'}")
    print(f"  L2 角色层    角色 {len(ir.characters.characters)}"
          f"  行动元 {len(ir.characters.actants)}"
          f"  目标对撞 {len(ir.characters.goal_collisions())} 处")
    print(f"  L3 承诺层    承诺 {len(ir.commitment.commitments)}"
          f"  未兑现 {len(ir.commitment.unsatisfied())}")
    print()
    print("场景骨架（Genette + McKee + Todorov）：")
    print(f"  {'id':<5}{'标题':<20}{'价值翻转':<10}{'结果':<10}{'情绪':>6}  聚焦者")
    for s in ir.ordered_scenes():
        print(f"  {s.id:<5}{s.title:<20}"
              f"{s.value_charge_start}→{s.value_charge_end:<8}"
              f"{s.outcome.value:<10}{s.emotion:>6.2f}  {s.focalizer}")
    anach = ir.anachronies()
    print(f"  时序倒错：{[a.id for a in anach] if anach else '无（顺叙）'}")

    # ---------------------------------------------------------------- 3
    head(3, "正文")
    print(render_text(ir)[:1200])
    print(f"\n…（全文 {ir.word_count()} 字，已写入 {OUT / 'novel.md'}）")

    # ---------------------------------------------------------------- 4
    head(4, "结构体检")
    report = run_all(ir)
    # 反 slop **只通报，不进健康分** —— 与 `cli.cmd_audit` 同一口径。
    # 此前这里用 `report.add(...)`，同一个 IR 在 demo 与 CLI 里显示不同的分，
    # 属于漂移（先例早已存在，见 `Report.add_advisory` 的说明），已对齐。
    report.add_advisory(*scan_ir(ir))
    print(report.render(f"{ir.title} · 体检"))
    # 两个数字必须**一起**打。只打健康分的话，这个分数一次上移约 6 分，
    # 看起来像「故事变好了」，实际只是工艺信号不再扣结构分。
    print(f"\n  结构分 {report.score()}/100（**不含**工艺信号）")
    print(f"  工艺提示 {len(report.advisory)} 条（只通报，不扣分）")

    # ---------------------------------------------------------------- 5
    head(5, "观众模拟")
    sim = AudienceSimulator(gen)
    aud = sim.run(ir)
    print(aud.render())

    # ---------------------------------------------------------------- 6
    head(6, "A/B 对比（观众模拟的主要用法）")
    # 用同一个想法但更长的篇幅做对照 —— 检验「加内容是否等于更好」
    ir_long = LoomPipeline(gen).run(
        idea,
        medium=Medium.NOVEL,
        arc_shape=ArcShape.MAN_IN_A_HOLE,
        scene_count=10,
        words_per_scene=600,
    ).ir
    print(sim.ab(ir, ir_long, label_a="6 场版", label_b="10 场版").render())

    # ---------------------------------------------------------------- 7
    head(7, "校准（把先验变成预测的唯一途径）")
    sigs = scene_signals(ir)
    observed = [1.0, 0.95, 0.91, 0.88, 0.85, 0.83]  # 假想的真实留存数据
    cal = sim.calibrate(observed, BINGE_WEB_NOVEL, sigs)
    print(f"观测留存    {observed}")
    print(f"拟合结果    base_hazard={cal['base_hazard']:.4f}"
          f"  RMSE={cal['rmse']:.4f}  样本 {cal['n']}")
    print(f"说明        {cal['note']}")
    print("\n校准后重跑：")
    print(sim.run(ir, personas=["binge_web_novel"], qualitative=False).render())

    # ---------------------------------------------------------------- 8
    head(8, "合规（AI 参与度计量）")
    pl = ProvenanceLedger()
    for s in ir.scenes:
        pl.record(
            chunk_id=f"chunk_{s.id}",
            scene_id=s.id,
            origin=s.origin,
            model_id=s.model_id,
            prompt_version=s.prompt_version,
            human_edit_ratio=0.0,  # 全自动产出，人工改写比例为 0
            char_count=len(s.prose or ""),
        )
    pl.attach(ir)
    print(pl.report(ir).render(f"{ir.title} · 合规"))

    # ---------------------------------------------------------------- 9
    head(9, "多路渲染（同一 IR，不同媒介视图）")
    renderers = {
        "novel.md": render_text(ir),
        "outline.md": render_outline(ir),
        "script.fountain": render_fountain(ir),
        "storyboard.json": render_storyboard(ir),
        "story.ink": render_ink(ir),
        "script.rpy": render_renpy(ir),
        "ir.json": ir.to_json(),
        "audience.json": json.dumps(aud.to_dict(), ensure_ascii=False, indent=2),
    }
    for name, content in renderers.items():
        (OUT / name).write_text(content, encoding="utf-8")
        print(f"  {name:<20} {len(content):>9,} 字符")
    print(f"\n全部写入 {OUT}")

    # ---------------------------------------------------------------- 10
    head(10, "Token 记账")
    print(ledger.render())
    print("\n（离线参考生成器的 token 为粗估；接真模型后即为真实计费口径）")

    print()
    print("═" * 64)
    print("  端到端验证完成。")
    print("═" * 64)
    return 0 if report.passed() else 1


if __name__ == "__main__":
    raise SystemExit(main())
