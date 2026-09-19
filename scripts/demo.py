"""端到端 demo：证明这套 IR 不是纸面设计。

跑法：
    .venv/Scripts/python.exe scripts/demo.py

流程：
    Idea -> IR 构建 -> schema 往返校验 -> 结构体检 -> 反 slop
         -> lore 激活 -> 5 种渲染器 -> 2.0 运行时 -> 随机通关测试 -> 合规报告
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from examples.demo_story import build_demo_ir  # noqa: E402
from keel.audit.anti_slop import scan_ir, scan_slop  # noqa: E402
from keel.ir.models import NarrativeIR  # noqa: E402
from keel.provenance.meter import ProvenanceLedger  # noqa: E402
from keel.policy import PolicyError  # noqa: E402
from keel.render import (  # noqa: E402
    render_fountain,
    render_ink,
    render_renpy,
    render_storyboard,
    render_text,
)
from keel.render.text import render_outline  # noqa: E402
from keel.runtime.director import StoryRuntime, randomized_playthroughs  # noqa: E402
from keel.validators import registry_stats, run_all  # noqa: E402

OUT = ROOT / "out"
BAR = "═" * 68


def section(n: int, title: str) -> None:
    print(f"\n{BAR}\n {n}. {title}\n{BAR}")


def main() -> int:
    OUT.mkdir(exist_ok=True)

    # ---------------------------------------------------------------- 1
    section(1, "构建 Narrative IR（三层正交）")
    ir = build_demo_ir()
    print(f"  标题        {ir.title}")
    print(f"  媒介        {ir.medium.value}")
    print(f"  弧线        {ir.commitment.arc_shape.value}")
    print(f"  L1 情节层   {len(ir.plot.events)} 个事件，{len(ir.plot.links)} 条因果边")
    print(f"  L2 角色层   {len(ir.characters.characters)} 个角色，"
          f"{len(ir.characters.actants)} 条行动元绑定")
    print(f"  L3 承诺层   {len(ir.commitment.commitments)} 条作者承诺")
    print(f"  场景        {len(ir.scenes)} 个")
    print(f"  谜题台账    {len(ir.enigmas)} 条")
    print(f"  Lore 条目   {len(ir.lore.entries)} 条")
    print(f"  Storylet    {len(ir.storylets)} 块")
    print(f"  IR 指纹     {ir.fingerprint()}")

    # ---------------------------------------------------------------- 2
    section(2, "Schema 往返校验（IR 是硬契约，不是文档）")
    raw = ir.to_json()
    ir2 = NarrativeIR.from_json(raw)
    same = ir.fingerprint() == ir2.fingerprint()
    print(f"  序列化       {len(raw):,} 字符")
    print(f"  往返指纹一致 {'✓ 是' if same else '✗ 否'}")
    try:
        bad = dict(ir.model_dump())
        bad["unknown_field_xyz"] = 1
        NarrativeIR.model_validate(bad)
        print("  extra=forbid ✗ 未生效")
    except Exception:
        print("  extra=forbid ✓ 未知字段被拒绝（schema 是硬约束）")
    try:
        from keel.ir.models import StateDelta
        StateDelta(entity_id="x", attribute="y", before=1, after=1)
        print("  零增量拒绝   ✗ 未生效")
    except Exception:
        print("  零增量拒绝   ✓ 零增量 StateDelta 被拒绝")

    # ---------------------------------------------------------------- 3
    # 数量从 registry 取，不手写 —— 手写的数字必然漂移。
    # （这个位置原先硬编码着一个早已过期的数字，且没有任何机制发现它。）
    _st = registry_stats()
    section(
        3,
        f"结构体检（{_st['gating']} 个校验器 + {_st['reports']} 个报表项）",
    )
    report = run_all(ir)
    report.add(*scan_ir(ir))
    print(report.render(f"{ir.title} · 故事体检报告"))

    # ---------------------------------------------------------------- 4
    section(4, "反 slop 扫描（单场景细看）")
    sc3 = ir.scene("sc3")
    rep = scan_slop(sc3.prose or "", scene_id="sc3")
    print(f"  场景            {sc3.title}")
    print(f"  去 AI 味得分    {rep.score}/100")
    print(f"  比喻密度        {rep.metaphor_density}/句")
    print(f"  句长变异系数    {rep.sentence_len_cv}")
    print(f"  句首重复率      {rep.repetition_ratio:.0%}")
    print("  命中：")
    for h in rep.hits:
        print(f"    · {h.kind} ×{h.count}  例：{h.sample!r}")
    print(f"\n  原文：{sc3.prose}")

    # ---------------------------------------------------------------- 5
    section(5, "Lore 激活（工业字段体系：关键词 + 预算 + 递归）")
    probe = "沈砚从怀里掏出腰牌，锦衣卫的纹样在雪光里很刺眼。"
    print(f"  探针文本  {probe}\n")
    active = ir.lore.compile(probe, budget_tokens=400)
    for e in active:
        tag = "常驻" if e.is_constant else "关键词"
        print(f"  [{tag}] order={e.order:>3}  {e.id}")
        print(f"          keys={e.keys} logic={e.logic.value} pos={e.position.value}")
        print(f"          {e.content[:56]}")
    print(f"\n  激活 {len(active)}/{len(ir.lore.entries)} 条（预算 400 tokens）")
    print("  注：递归激活使「沈砚」命中后自动拉起其关联条目。")

    # ---------------------------------------------------------------- 6
    section(6, "渲染：同一 IR -> 5 种媒介（2.0 免费继承）")
    # 网文正文受策略闸门约束（起点/番茄/晋江 禁 AI 直出正文，见 keel/policy.py）。
    # 这里**故意不加** force_prose —— demo 应该展示默认行为，而不是绕过它。
    try:
        novel_md = render_text(ir, show_meta=True)
    except PolicyError as exc:
        novel_md = None
        print(f"  ⚠ novel.md 未生成：{exc}\n")
    files = {
        "script.fountain": render_fountain(ir),
        "storyboard.json": render_storyboard(ir),
        "story.ink": render_ink(ir),
        "script.rpy": render_renpy(ir),
        "outline.md": render_outline(ir),
        "ir.json": raw,
    }
    if novel_md is not None:
        files["novel.md"] = novel_md
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
        print(f"  {name:<20} {len(content):>8,} 字符")
    print(f"\n  输出目录 {OUT}")
    print("  要点：文本只是 IR 的一个视图；换 renderer 即换媒介，无需重写。")

    # ---------------------------------------------------------------- 7
    section(7, "2.0 运行时：Waypoint 骨架 + Storylet 池 + Director")
    rt = StoryRuntime(ir, seed=7)
    print(f"  Waypoint 序列   {rt.waypoints}")
    print(f"  初始品质        {rt.state.qualities}\n")
    for line in rt.play(turns=6):
        print("  " + line)
    print(f"\n  最终品质        {rt.state.qualities}")
    print("  要点：Director 用戏剧弧光约束显著性选择，防意外坏结局；")
    print("        合法集为空时回落到兜底块 —— 永不给玩家零个选项。")

    # ---------------------------------------------------------------- 8
    section(8, "随机化通关测试（Emily Short 的测试方法）")
    res = randomized_playthroughs(ir, runs=500, turns=25)
    print(f"  运行            {res['runs']} 次 × 25 回合")
    print(f"  零选项事件      {res['zero_option_events']}")
    print(f"  死路            {res['dead_ends']}")
    print(f"  从未触达的块    {res['never_reached'] or '无 ✓'}")
    print("  使用率最高：")
    for sid, ratio in res["overused"]:
        print(f"    {sid:<16} {ratio:6.1%}")
    print("\n  Waypoint 触达分布：")
    mx = max(1, max(res["waypoint_hits"].values()))
    for wid, hits in res["waypoint_hits"].items():
        print(f"    {wid:<8} {'█' * int(36 * hits / mx):<36} {hits}")

    # ---------------------------------------------------------------- 9
    section(9, "AI 参与度与合规报告")
    ledger = ProvenanceLedger()
    for s in ir.scenes:
        ledger.record(
            chunk_id=f"chunk_{s.id}", scene_id=s.id, origin=s.origin,
            model_id=s.model_id or "claude-sonnet-4.6",
            prompt_version="prose.v3",
            human_edit_ratio=0.6, char_count=len(s.prose or ""),
        )
    ledger.attach(ir)
    part = ledger.report(ir)
    print(part.render(f"{ir.title} · AI 参与度与合规报告"))
    (OUT / "compliance.json").write_text(part.to_json(), encoding="utf-8")
    print("\n  已写入 out/compliance.json")

    # ---------------------------------------------------------------- 10
    section(10, "结构模板插件（方法论中立）")
    from keel.ir.templates import list_templates

    for t in list_templates():
        print(f"  {t.id:<22} {t.name:<18} {len(t.beats):>2} 节拍  ← {t.origin}")
    print("\n  要点：好莱坞 beat sheet 与起承转合、以及 Reagan 六种实证弧线平级共存。")
    print("        方法论不是 prompt 前缀，是可插拔的「结构模板 + 校验器」两件套。")

    print(f"\n{BAR}\n 完成。产物见 {OUT}\n{BAR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
