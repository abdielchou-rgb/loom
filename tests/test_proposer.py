"""提案协议（Proposer + 裁决 + 遥测）—— 测试先行。

跑法：
    .venv/Scripts/python.exe tests/test_proposer.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `tests/test_tom.py` 同风格。

── 本文件测的是一条**可机检的性质**，不是一个态度 ────────

「永不静默改写」如果只是一句承诺，它迟早会破 —— 因为没有任何测试
会在它破的时候变红。本文件把它变成三条断言：

  1. `Proposer.run()` **不改动任何目标字段**（第 2 组：跑前跑后逐字段比对）
  2. **采纳也不改动目标字段**（第 2 组：`decide(accept=True)` 之后目标字段
     仍然原样）—— 采纳是一个**决定**，不是一次**应用**。
     把这两件事分开，正是「作者保留裁决权」在数据上的含义。
  3. 唯一能翻转 `Diff.status` 的入口是 `decide()` / `NarrativeIR.accept_proposal()`
     （第 5、6 组）

`tests/test_proposal.py` 测的是状态机本身；本文件测的是**流水线怎么用它**。

── 第 8 组是变异测试 ──────────────────────────────────

干净基线上必须**一条提案都没有**。只断言「缺陷 IR 上有提案」是不够的 ——
一个「永远产出 N 条提案」的实现也能通过。所以两边都要断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.ir.proposal import DiffStatus  # noqa: E402
from tests.fixtures import MUTATIONS, clean_copy  # noqa: E402


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
# 构造工具
# ---------------------------------------------------------------------------


def _flawed_ir():
    """带真实结构缺陷的 IR：用现成的示例（3 错 5 警，含 storylet）。"""
    from examples.demo_story import build_demo_ir

    return build_demo_ir()


def _ir_with_one_defect(code: str = "commitment_satisfied"):
    """干净基线 + 恰好一个变异 —— 用来做精确的单点断言。"""
    ir = clean_copy()
    MUTATIONS[code][0](ir)
    return ir


def _snapshot_without_proposals(ir) -> dict:
    """IR 的逐字段快照，**排除 proposals**。

    这是「永不静默改写」的判据载体：Proposer 只许新增 proposals，
    不许动别的任何字段。把 proposals 排除掉，剩下的必须逐字节相同。
    """
    data = ir.model_dump(mode="json")
    data.pop("proposals", None)
    return data


# ---------------------------------------------------------------------------
# 1. 基本转换
# ---------------------------------------------------------------------------


def test_basic_conversion(t: T) -> None:
    from loom.pipeline.engines import Proposer
    from loom.validators import run_all

    t.group("1. 结构问题 -> 待裁决提案")

    ir = _flawed_ir()
    report = run_all(ir)
    n_severe = len(report.errors) + len(report.warnings)
    t.ok(n_severe > 0, f"缺陷 IR 有严重发现（{n_severe} 条）")

    diffs = Proposer().run(ir, report)
    t.ok(bool(diffs), f"产出了提案（{len(diffs)} 条）")
    t.eq(len(ir.proposals), len(diffs), "提案被登记进 ir.proposals")

    codes = {f.code for f in [*report.errors, *report.warnings]}
    for d in diffs:
        t.eq(d.status, DiffStatus.PENDING, f"{d.id} 默认是 pending（绝不默认生效）")
        t.ok(bool(d.rationale.strip()), f"{d.id} 有 rationale（Horvitz 1999：必须能解释）")
        t.ok(bool(d.source_card), f"{d.id} 有 source_card")
        t.ok(d.source_card.startswith("validator:"), f"{d.id} 的 source_card 指向校验器")
        t.ok(
            d.source_card.split(":", 1)[1] in codes,
            f"{d.id} 的 source_card 对应一条真实发现",
        )
        t.ok(d.field != "", f"{d.id} 有字段名")
        t.ok(bool(d.after), f"{d.id} 有提案内容")

    ids = [d.id for d in diffs]
    t.eq(len(ids), len(set(ids)), "提案 id 互不重复")


# ---------------------------------------------------------------------------
# 2. 永不静默改写（跑不改，采纳也不改）
# ---------------------------------------------------------------------------


def test_never_silently_rewrites(t: T) -> None:
    from loom.pipeline import LoomPipeline
    from loom.pipeline.engines import Proposer
    from loom.llm import MockGenerator
    from loom.validators import run_all

    t.group("2. 永不静默改写：产出不改，采纳也不改")

    ir = _flawed_ir()
    report = run_all(ir)
    before = _snapshot_without_proposals(ir)

    diffs = Proposer().run(ir, report)
    t.ok(bool(diffs), "有提案可测")
    t.eq(_snapshot_without_proposals(ir), before, "Proposer.run() 不改动任何目标字段")

    # 采纳 = 一个决定，不是一次应用。目标字段必须**仍然原样**。
    pipe = LoomPipeline(MockGenerator())
    target = diffs[0]
    pipe.decide(ir, target.id, accept=True)
    t.eq(target.status, DiffStatus.ACCEPTED, "裁决已落到提案上")
    t.eq(
        _snapshot_without_proposals(ir),
        before,
        "采纳之后目标字段仍未改动 —— 采纳是决定，不是应用",
    )


# ---------------------------------------------------------------------------
# 3. 幂等与确定性
# ---------------------------------------------------------------------------


def test_idempotent(t: T) -> None:
    from loom.pipeline.engines import Proposer
    from loom.validators import run_all

    t.group("3. 幂等与确定性")

    ir = _flawed_ir()
    report = run_all(ir)
    first = Proposer().run(ir, report)
    second = Proposer().run(ir, run_all(ir))

    t.eq(second, [], "第二次 run 不新增提案（幂等）")
    t.eq(len(ir.proposals), len(first), "ir.proposals 没有累积副本")
    ids = [d.id for d in ir.proposals]
    t.eq(len(ids), len(set(ids)), "id 仍然唯一")

    # 确定性：同样的输入，同样的 id 序列。
    other = _flawed_ir()
    third = Proposer().run(other, run_all(other))
    t.eq([d.id for d in third], [d.id for d in first], "确定性 id（同输入同 id）")


# ---------------------------------------------------------------------------
# 4. 只装结构类问题
# ---------------------------------------------------------------------------


def test_only_structural(t: T) -> None:
    """判据是**可机检的**：只有 registry 里注册过的校验器才产出结构类发现。

    这条测试刻意用**真实的**文风/工艺 code，而不是编一个像 code 的字符串：
    `dress.py` 与 `transportation.py` 产出的是 `audit:*`（不是 `dress:` /
    `transport:`），cognitive 产出的是不带前缀的 `cognitive_load_window`。
    原先的实现在这三条上全部漏判 —— 手写的 code 前缀表必然漂移。
    """
    from loom.ir.enums import Severity
    from loom.pipeline.engines import Proposer
    from loom.validators.base import Finding, Report

    t.group("4. 提案队列只装结构类问题")

    ir = clean_copy()
    report = Report()
    report.add(
        Finding(code="slop:cliche", severity=Severity.WARN, message="陈词滥调"),
        Finding(code="craft:micro_tension_low", severity=Severity.WARN, message="缺张力"),
        Finding(code="audit:style_drift", severity=Severity.WARN, message="风格漂移"),
        Finding(code="audit:transportation", severity=Severity.WARN, message="传输度低"),
        Finding(code="audit:over_explained", severity=Severity.WARN, message="解释过度"),
        Finding(code="cognitive_load_window", severity=Severity.WARN, message="超载"),
        Finding(code="commitment_satisfied", severity=Severity.ERROR, message="承诺未兑现"),
    )
    diffs = Proposer().run(ir, report)

    t.eq(len(diffs), 1, "只把结构类问题转成提案（文风/工艺类被跳过）")
    t.eq(diffs[0].source_card, "validator:commitment_satisfied", "剩下的正是结构类那条")

    # 反向对照：如果判据换成前缀黑名单，上面那 5 条里至少有 2 条会漏进来。
    from loom.validators import available

    non_registered = [
        "slop:cliche",
        "craft:micro_tension_low",
        "audit:style_drift",
        "audit:transportation",
        "audit:over_explained",
        "cognitive_load_window",
    ]
    t.eq(
        sorted(c for c in non_registered if c in set(available())),
        [],
        "这 6 个 code 都不在 registry 里 —— 判据「注册过」才是对的",
    )


# ---------------------------------------------------------------------------
# 5. 裁决 + 决策遥测
# ---------------------------------------------------------------------------


def test_decide_and_telemetry(t: T) -> None:
    from loom.llm import MockGenerator
    from loom.pipeline import LoomPipeline
    from loom.pipeline.engines import Proposer
    from loom.validators import run_all

    t.group("5. 裁决 + 决策遥测")

    ir = _flawed_ir()
    Proposer().run(ir, run_all(ir))
    pipe = LoomPipeline(MockGenerator())

    t.eq(pipe.telemetry.decisions, 0, "初始零裁决")
    t.eq(pipe.telemetry.accept_rate, 0.0, "零裁决时采纳率是 0.0（不是 100%，也不抛错）")

    ids = [d.id for d in ir.proposals]
    t.ok(len(ids) >= 3, f"至少有 3 条提案可裁决（实际 {len(ids)}）")

    pipe.decide(ir, ids[0], accept=True, story_at="第 3 章")
    t.eq(pipe.telemetry.decisions, 1, "裁决数 +1")
    t.eq(pipe.telemetry.accepted, 1, "采纳数 +1")
    t.eq(pipe.telemetry.accept_rate, 1.0, "采纳率 1/1")

    pipe.decide(ir, ids[1], accept=False)
    t.eq(pipe.telemetry.decisions, 2, "裁决数 2")
    t.eq(pipe.telemetry.accept_rate, 0.5, "采纳率 1/2")

    # 先接受再拒绝 → conflicted。**它照常进遥测**（计入分母）——
    # 把它排除会让采纳率虚高，那正是这套指标要防的自欺。
    pipe.decide(ir, ids[0], accept=False)
    t.eq(ir.proposals[0].status, DiffStatus.CONFLICTED, "同一条先接受再拒绝 → conflicted")
    t.eq(pipe.telemetry.decisions, 3, "conflicted 计入裁决数")
    t.eq(pipe.telemetry.conflicted, 1, "conflicted 计数")
    t.eq(
        round(pipe.telemetry.accept_rate, 4),
        round(1 / 3, 4),
        "采纳率 1/3（conflicted 在分母里）",
    )

    # 记录的是**裁决当时**的快照，不是对 Diff 的引用。
    rec = next(r for r in pipe.telemetry.records if r.diff_id == ids[0])
    t.eq(rec.story_at, "第 3 章", "story_at 由调用方传入（本模块不取时钟）")

    stats = pipe.telemetry.stats()
    t.eq(stats["decisions"], 3, "stats() 口径一致")
    t.ok(
        sum(stats["by_field"].values()) == stats["decisions"],
        "按字段分布的合计 == 裁决数（分区定义）",
    )
    t.ok(
        sum(stats["by_source_card"].values()) == stats["decisions"],
        "按来源卡分布的合计 == 裁决数",
    )


# ---------------------------------------------------------------------------
# 6. 一键裁决 + 非法 id
# ---------------------------------------------------------------------------


def test_decide_all_and_bad_id(t: T) -> None:
    from loom.llm import MockGenerator
    from loom.pipeline import LoomPipeline
    from loom.pipeline.engines import Proposer
    from loom.validators import run_all

    t.group("6. 一键裁决 + 非法 id")

    ir = _flawed_ir()
    Proposer().run(ir, run_all(ir))
    pipe = LoomPipeline(MockGenerator())
    n = len(ir.pending_proposals())
    t.ok(n > 0, f"有待裁决提案（{n} 条）")

    done = pipe.decide_all(ir, accept=True)
    t.eq(len(done), n, "一键采纳处理了全部待裁决提案")
    t.eq(ir.pending_proposals(), [], "没有遗留待裁决项")
    t.eq(pipe.telemetry.decisions, n, "遥测记录了 n 次裁决")
    t.eq(pipe.telemetry.accept_rate, 1.0, "全部采纳 → 采纳率 1.0")

    # 裁决不存在的 id 是编程错误，必须炸 —— 静默返回 None 会让调用方
    # 以为裁决成功了。
    try:
        pipe.decide(ir, "prop_不存在", accept=True)
        t.ok(False, "裁决不存在的 id 应当抛错")
    except KeyError:
        t.ok(True, "裁决不存在的 id 抛 KeyError")
    t.eq(pipe.telemetry.decisions, n, "失败的裁决不进遥测")


# ---------------------------------------------------------------------------
# 7. 上限与字段映射
# ---------------------------------------------------------------------------


def test_cap_and_field_map(t: T) -> None:
    from loom.pipeline.engines import _FIELD_OF, Proposer
    from loom.validators import run_all

    t.group("7. 上限与字段映射")

    ir = _flawed_ir()
    report = run_all(ir)
    full = Proposer().run(_flawed_ir(), report)
    t.ok(len(full) > 1, f"提案数 > 1（实际 {len(full)}）")

    capped_ir = _flawed_ir()
    capped = Proposer(max_proposals=1).run(capped_ir, run_all(capped_ir))
    t.eq(len(capped), 1, "max_proposals 生效")
    t.eq(len(capped_ir.proposals), 1, "被截断的提案不登记")

    # 字段映射：判据是「映射到的字段名**真的存在于某个 IR 模型上**」，
    # 而不是「值等于某个手写常量」—— 后者会随实现漂移，前者不会。
    #
    # 命名空间**从 IR 模块现扫**，不手写模型清单：
    # 手写清单漏一个模型就会产生假失败（这里第一次写就漏了 WorldRule 与
    # CharacterBeliefState），而假失败会让人去改断言而不是改代码。
    import inspect as _inspect

    from loom.ir import models as M
    from loom.ir import proposal as P
    from loom.ir import tom as TOM
    from loom.ir.base import LoomModel

    namespace: set[str] = set()
    for module in (M, TOM, P):
        for _, obj in _inspect.getmembers(module, _inspect.isclass):
            if issubclass(obj, LoomModel) and obj is not LoomModel:
                namespace |= set(obj.model_fields)

    t.ok(len(namespace) > 50, f"IR 字段命名空间已扫出（{len(namespace)} 个字段名）")
    bad = sorted({v for v in _FIELD_OF.values() if v not in namespace})
    t.eq(bad, [], "所有字段映射都落在真实存在的 IR 模型字段上")

    # 覆盖度：注册的校验器越多，这张表越该跟上。缺项不算错（回退成 code
    # 本身，只是遥测粒度变粗），但覆盖率不该悄悄塌掉。
    #
    # 分母是**门禁项**，不是全部注册项 —— 报表项（`REPORTS`）按设计
    # 只出 INFO，而 `Proposer` 只消费 ERROR/WARN，所以报表项**永远**
    # 不会产出提案，给它们登记字段映射就是登记死数据。
    #
    # 这条修正是加三个合规检测器时被迫发现的：按 `available()` 全量算，
    # 覆盖率会从「30/32」掉到「30/35」并失败，而**正确的反应不是补三行
    # 永远不会用到的映射**，是承认分母取错了 —— 又是一次「手写/派生的
    # 口径要落在语义上（会不会产出提案），不是落在语法上（注没注册）」。
    from loom.validators import REPORTS, available

    gating = [c for c in available() if c not in REPORTS]
    covered = [c for c in gating if c in _FIELD_OF]
    t.ok(
        len(covered) >= len(gating) - 2,
        f"字段映射覆盖了绝大多数门禁项（{len(covered)}/{len(gating)}"
        f"，另有 {len(available()) - len(gating)} 个报表项按设计不产出提案）",
    )

    for d in full:
        t.ok(bool(d.field), f"{d.id} 有字段名（未登记 code 回退成 code 本身）")


# ---------------------------------------------------------------------------
# 8. 变异测试：干净基线上零提案
# ---------------------------------------------------------------------------


def test_mutation_clean_has_no_proposals(t: T) -> None:
    from loom.pipeline.engines import Proposer
    from loom.validators import run_all

    t.group("8. 变异测试：干净基线零提案")

    for medium in ("novel", "micro_drama"):
        from loom.ir.enums import Medium

        ir = clean_copy(Medium(medium))
        diffs = Proposer().run(ir, run_all(ir))
        t.eq(diffs, [], f"{medium} 干净基线零提案（没有结构问题就没有待办）")

    # 反向对照：注入一个结构缺陷，提案必须出现。
    ir = _ir_with_one_defect("commitment_satisfied")
    diffs = Proposer().run(ir, run_all(ir))
    t.ok(
        any(d.source_card == "validator:commitment_satisfied" for d in diffs),
        "注入「承诺未兑现」后产出对应提案（证明断言测的是缺陷，不是常数）",
    )
    t.eq(
        [d.field for d in diffs if d.source_card == "validator:commitment_satisfied"],
        ["commitments"],
        "该提案的字段是 commitments",
    )


# ---------------------------------------------------------------------------
# 9. CriticLoop 接线
# ---------------------------------------------------------------------------


def test_critic_loop_wiring(t: T) -> None:
    from loom.llm import MockGenerator
    from loom.pipeline.engines import CriticLoop

    t.group("9. CriticLoop 接线")

    ir = _flawed_ir()
    before = _snapshot_without_proposals(ir)
    loop = CriticLoop(MockGenerator(), max_rounds=0)
    _, log = loop.run(ir)
    t.ok(bool(ir.proposals), "CriticLoop 默认产出提案")
    t.ok(
        any("不自动应用" in line for line in log),
        "日志明确写出「不自动应用」",
    )
    t.eq(
        _snapshot_without_proposals(ir),
        before,
        "CriticLoop 也没改动任何目标字段",
    )

    # propose=False 时完全不产出提案 —— 开关必须真的有效。
    ir2 = _flawed_ir()
    CriticLoop(MockGenerator(), max_rounds=0, propose=False).run(ir2)
    t.eq(ir2.proposals, [], "propose=False 时不产出提案")


# ---------------------------------------------------------------------------


def main() -> int:
    t = T()
    test_basic_conversion(t)
    test_never_silently_rewrites(t)
    test_idempotent(t)
    test_only_structural(t)
    test_decide_and_telemetry(t)
    test_decide_all_and_bad_id(t)
    test_cap_and_field_map(t)
    test_mutation_clean_has_no_proposals(t)
    test_critic_loop_wiring(t)

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
