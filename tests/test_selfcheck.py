"""投稿前合规自检 —— 单元测试。

跑法：
    .venv/Scripts/python.exe tests/test_selfcheck.py

零依赖，与 `tests/test_rhythm.py` 同风格。实现先于测试，故同样做了
变异测试补偿（见文件末尾的实测记录）。

── 本文件要钉死的三件事 ─────────────────────────────────

1. **「待人工确认」必须存在，且不算阻塞也不算通过。**
   把它并进「通过」= 宣称 Keel 全查过了；并进「阻塞」= 这个命令
   永远没人能用（任何稿子都有平台侧 Keel 看不到的信息）。
   单列一态是唯一诚实的做法。

2. **维度对照表的覆盖状态是派生的。**
   手写「✅/❌」必然漂移。第一版只认 registry，结果 `dress` / `anti_slop`
   明明存在却显示「Keel 不做」—— **派生口径取错比手写更容易骗人**，
   因为它看起来是算出来的。故断言「覆盖数 == 实际能力数」。

3. **内容编号由内容派生，不是时间戳。**
   申诉时要证明「你交的就是这份」，会变的编号做不到。
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

    def group(self, name: str) -> None:
        print(f"\n  {name}")


# ---------------------------------------------------------------------------
# 样本：两条 IR（纯人工 / 全 AI）
# ---------------------------------------------------------------------------


def _human_ir():
    from keel.ir.models import Medium
    from tests.fixtures import clean_copy

    ir = clean_copy(Medium.NOVEL)  # 基线已把 origin 全设为 HUMAN
    return ir


def _ai_ir():
    from keel.ir.enums import ChunkOrigin
    from keel.ir.models import Medium
    from tests.fixtures import clean_copy

    ir = clean_copy(Medium.NOVEL)
    for s in ir.scenes:
        s.origin = ChunkOrigin.AI_GENERATED
        s.model_id = "test-model-v1"
        s.prompt_version = "prose@v4"
    ir.provenance = []
    return ir


def _ai_ir_partial_trace():
    """AI 生成 + **溯源只覆盖一部分场景**。

    这是最容易漏测的一条路径：占比数字报得出来，但**不可证明**。
    占比本身可能没越线，而「证明不了」本身就是阻塞 ——
    申诉时拿不出的证据等于没有。
    """
    ir = _ai_ir()
    ir.provenance = ir.provenance[:1] if ir.provenance else []
    # _ai_ir 清空了 provenance，故这里手工只登记第一个场景
    from keel.ir.models import Provenance

    ir.provenance = [
        Provenance(
            chunk_id=f"chunk_{ir.scenes[0].id}",
            scene_id=ir.scenes[0].id,
            origin=ir.scenes[0].origin,
            model_id=ir.scenes[0].model_id,
            char_count=len(ir.scenes[0].prose or ""),
        )
    ]
    return ir


# ---------------------------------------------------------------------------
# 1. 法律义务层
# ---------------------------------------------------------------------------


def test_legal_layer(t: T) -> None:
    from keel.audit.selfcheck import BLOCKED, MANUAL, OK, WARN, pre_submit_check

    t.group("1. 法律义务层")

    human = pre_submit_check(_human_ir())
    by_key = {i.key: i for i in human.items}
    t.ok(by_key["ai_ratio"].status != BLOCKED, "纯人工 → 占比不阻塞")
    t.eq(by_key["trace_coverage"].status, OK, "溯源齐 → 覆盖率可证明")
    t.eq(by_key["explicit_label"].status, OK, "无 AI 参与 → 无需标识")

    ai = pre_submit_check(_ai_ir())
    by_key = {i.key: i for i in ai.items}
    t.eq(by_key["ai_ratio"].status, BLOCKED, "AI 占比 100% → 硬阻塞")
    t.eq(by_key["explicit_label"].status, MANUAL, "有 AI 参与 → 标识待作者确认")
    t.eq(by_key["implicit_label"].status, MANUAL, "隐式标识同样待确认")

    # 溯源不全：占比**报得出来但证明不了** —— 这本身就是硬阻塞。
    # 这条路径原先没测到（变异测试抓出来的盲区）：
    # AI IR 的 provenance 被清空后会被自动补全，覆盖率恒为 100%，
    # 于是「证明不了」这个分支从来没被执行过。
    partial = pre_submit_check(_ai_ir_partial_trace())
    pkey = {i.key: i for i in partial.items}
    t.ok(
        partial.participation.trace_coverage < 1.0,
        f"溯源确实不全（{partial.participation.trace_coverage:.0%}）",
    )
    t.eq(pkey["trace_coverage"].status, BLOCKED, "溯源不全 + AI 占比 >0 → 硬阻塞")

    # 对照：同样的不全，但**没有 AI 参与** → 只是留意，不是阻塞。
    # 证明不了「0%」与证明不了「100%」的责任不同。
    human_partial = _human_ir()
    human_partial.provenance = human_partial.provenance[:1]
    hp = pre_submit_check(human_partial)
    hkey = {i.key: i for i in hp.items}
    t.ok(hp.participation.trace_coverage < 1.0, "人工稿同样溯源不全")
    t.eq(hkey["trace_coverage"].status, WARN, "无 AI 参与 → 溯源不全是留意，不是阻塞")


# ---------------------------------------------------------------------------
# 2. 三态：待人工确认既不是通过也不是阻塞
# ---------------------------------------------------------------------------


def test_manual_is_a_third_state(t: T) -> None:
    from keel.audit.selfcheck import pre_submit_check

    t.group("2. 「待人工确认」是独立的一态")

    for name, ir in (("纯人工", _human_ir()), ("全 AI", _ai_ir())):
        cl = pre_submit_check(ir)
        t.ok(len(cl.manual) > 0, f"{name}：仍有须人工确认的项（{len(cl.manual)}）")
        # 关键：MANUAL 既不计入 blockers，也不计入 warnings
        level, _note = cl.verdict()
        manual_keys = {i.key for i in cl.manual}
        blocked_keys = {i.key for i in cl.blockers}
        warn_keys = {i.key for i in cl.warnings}
        t.eq(manual_keys & blocked_keys, set(), f"{name}：MANUAL 不进 blockers")
        t.eq(manual_keys & warn_keys, set(), f"{name}：MANUAL 不进 warnings")
        t.ok(level in {"OK", "CAUTION", "BLOCKED"}, f"{name}：结论等级合法（{level}）")

    # 纯人工稿：没有阻塞。**但结论文案必须仍然提到待确认项** ——
    # 否则读者会以为「OK = 能投」。
    cl = pre_submit_check(_human_ir())
    note = cl.verdict()[1]
    t.ok(str(len(cl.manual)) in note, f"OK 结论里仍然报出待确认项数：{note}")


# ---------------------------------------------------------------------------
# 3. 维度对照表：覆盖状态是派生的
# ---------------------------------------------------------------------------


def test_dimensions_are_derived(t: T) -> None:
    from keel.audit.selfcheck import DIMENSIONS, _audit_capabilities, pre_submit_check
    from keel.validators import available

    t.group("3. 维度覆盖是派生的，不是手写的")

    cl = pre_submit_check(_human_ir())
    covered, total = cl.dimension_coverage
    t.eq(total, len(DIMENSIONS), "维度总数取自表本身")

    # 期望覆盖数：**现算**，不写死。
    # 这一条在补检测器后会自动上升，在表写错能力名后会自动下降 ——
    # 这才是「派生」的意义。
    registry = set(available())
    audit_mods = _audit_capabilities()
    expect = sum(
        1 for d in DIMENSIONS if d.keel and set(d.keel) <= (registry | audit_mods)
    )
    t.eq(covered, expect, f"覆盖数 == 现算的能力数（{covered}/{total}）")

    # 反例：任何一个维度的能力名写错（指向不存在的东西），
    # 它必须立刻掉出覆盖集 —— 这正是第一版 `audit:style_drift` 的教训
    # （那个 code 不在 registry 里，于是 dress 被误判成「Keel 不做」）。
    bad = [d.key for d in DIMENSIONS if d.keel and not d.covered]
    t.eq(bad, [], f"没有维度因能力名写错而掉出覆盖集（坏项：{bad}）")

    # audit 能力清单必须真的包含那几个模块
    t.ok("anti_slop" in audit_mods, "anti_slop 被识别为能力")
    t.ok("dress" in audit_mods, "dress 被识别为能力")
    t.ok("rhythm" in audit_mods, "rhythm 被识别为能力")

    # 「Keel 结构上不做」的维度必须名副其实：keel 为空
    structural = [d.key for d in DIMENSIONS if not d.keel]
    t.ok(len(structural) >= 3, f"至少三个维度被标为结构上不可检（{structural}）")
    for key in structural:
        d = next(x for x in DIMENSIONS if x.key == key)
        t.ok(not d.covered, f"{key}：无能力名 → 不覆盖")


# ---------------------------------------------------------------------------
# 4. 标识与元数据
# ---------------------------------------------------------------------------


def test_labels_and_metadata(t: T) -> None:
    from keel.audit.selfcheck import content_id, implicit_metadata, required_labels
    from keel.ir.models import Medium
    from tests.fixtures import clean_copy

    t.group("4. 显式标识 / 隐式标识 / 内容编号")

    ir = _human_ir()
    t.eq(required_labels(ir), [], "纯人工 → 无需标识")

    ai = _ai_ir()
    labels = required_labels(ai)
    t.ok(len(labels) >= 1, f"全 AI → 至少一条标识（{labels}）")
    t.ok(
        any("AI" in s for s in labels),
        "标识文案里必须出现「AI」（法规要求的是**显著标识**）",
    )

    # 微短剧额外一条（第 34 条：每集明显位置）
    md = clean_copy(Medium.MICRO_DRAMA)
    from keel.ir.enums import ChunkOrigin

    for s in md.scenes:
        s.origin = ChunkOrigin.AI_GENERATED
        s.model_id = "test-model-v1"
    t.ok(
        len(required_labels(md)) > len(labels),
        f"微短剧比小说多一条标识（{len(required_labels(md))} > {len(labels)}）",
    )

    meta = implicit_metadata(ai)
    t.eq(
        sorted(meta),
        sorted(["生成合成属性", "服务提供者名称或编码", "内容编号"]),
        "元数据三要素齐（《标识办法》要求）",
    )
    t.eq(meta["服务提供者名称或编码"], "test-model-v1", "提供者编码取 model_id")
    # 元数据里的编号必须真的来自 `content_id` —— 不能退化成常量
    # （变异测试抓出来的盲区：改成 "—" 时测试仍然全绿）。
    t.eq(meta["内容编号"], content_id(ai), "元数据编号 == content_id(ir)")

    # 内容编号：**由内容派生** —— 同一份 IR 两次算必须一样，
    # 改一个字就必须不同。时间戳/自增序号做不到这两点。
    t.eq(content_id(ai), content_id(ai), "同一份内容 → 同一编号")
    other = _ai_ir()
    other.title = ai.title + "（改后）"
    t.ok(content_id(other) != content_id(ai), "内容变了 → 编号必须变")


# ---------------------------------------------------------------------------
# 5. 报告可导出（申诉时用得上）
# ---------------------------------------------------------------------------


def test_export(t: T) -> None:
    import json

    from keel.audit.selfcheck import pre_submit_check

    t.group("5. 报告可导出")

    cl = pre_submit_check(_ai_ir())
    data = json.loads(cl.to_json())
    t.eq(data["level"], "BLOCKED", "JSON 里有结论等级")
    t.ok(data["counts"]["blocked"] >= 1, "JSON 里有阻塞计数")
    t.ok(data["dimension_coverage"]["total"] > 0, "JSON 里有维度覆盖")
    t.ok(len(data["regulations"]) == 2, "JSON 里有两层法规依据")
    t.ok(data["required_labels"], "JSON 里有必须贴的标识文案")
    t.ok(data["implicit_metadata"], "JSON 里有隐式标识元数据")

    text = cl.render()
    t.ok("不是" in text and "保证" in text, "渲染文本里有无保证声明")
    t.ok("媒体转述" in text, "渲染文本里标出了证据等级")


# ---------------------------------------------------------------------------
# 6. 红线：不提供反检测
# ---------------------------------------------------------------------------


def test_no_anti_detect(t: T) -> None:
    t.group("6. 红线：没有反检测出口")

    import keel.cli as cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    for word in ("anti-detect", "anti_detect", "降AI", "降 AI", "humanize", "洗稿"):
        t.ok(word not in src, f"CLI 里不存在 {word!r}")

    from keel.audit import selfcheck

    s = Path(selfcheck.__file__).read_text(encoding="utf-8")
    t.ok("反检测" in s, "自检模块**正面说明**了它不是反检测（不是回避话题）")


def main() -> int:
    print("═" * 64)
    print("  投稿前合规自检 —— 测试")
    print("═" * 64)
    t = T()
    try:
        test_legal_layer(t)
        test_manual_is_a_third_state(t)
        test_dimensions_are_derived(t)
        test_labels_and_metadata(t)
        test_export(t)
        test_no_anti_detect(t)
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
