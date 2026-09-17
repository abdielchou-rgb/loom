#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""觉察回显（`loom/provenance/awareness.py`）单元测试。

依据：Bhat et al., *Reactive Writers*, CHI 2026（arXiv:2603.10374）。
作者**察觉不到** AI 对自己方向的影响，却感觉完全掌控 ——
所以「你做了多少判断」必须在**写作时**可见，而不是申诉时才导出。

本模块**不生产新数据**，只把 `ir.proposals` 换个出口。因此测试的重心不是算法，
而是三条**设计claim**，每条都必须能被证伪：

  A. 数据来自 `ir.proposals`（持久化），**不是**内存态遥测 → 用 JSON 往返证明
  B. 只报数、不评判 → 断言输出里没有分数 / 百分比 / 评级词
  C. 判据是「作者做了多少判断」，不是「AI 生成了多少字」→ 断言输出不含字数

变异测试结果（改实现后本测试必须变红，已逐条实测）：

| 变异 | 结果 |
|---|---|
| `counts()` 把 `pending` 也算进 `decided` | 红（test_counts_split / test_pending_only） |
| `scenes_touched()` 改为数 `AI_GENERATED` | 红（test_scenes_touched_origin） |
| `awareness_line()` 在 total==0 时返回空串 | 红（test_no_proposals） |
| `awareness_block()` 去掉 CHI 2026 说明行 | 红（test_block_explains_why） |
| `awareness_line()` 追加「判断力 XX 分」 | 红（test_no_scoring） |

运行：`.venv/Scripts/python.exe tests/test_awareness.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loom.ir.enums import ChunkOrigin, Medium
from loom.ir.models import NarrativeIR
from loom.ir.proposal import Diff, DiffStatus
from loom.pipeline.engines import CriticLoop
from loom.provenance.awareness import (
    awareness_block,
    awareness_line,
    counts,
    scenes_touched,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    if not cond:
        print(f"  ✗ {name}  {detail}")
    else:
        print(f"  ✓ {name}")


def _mk_ir() -> NarrativeIR:
    """**必须用 `clean_copy`，不能用 `build_clean_ir`。**

    `build_clean_ir` 有模块级 `_CACHE`，返回的是**同一个对象**。
    本测试大量改写 `ir.proposals` 与 `scene.origin` ——
    直接在缓存对象上改会**污染同进程内后续所有 `build_clean_ir()` 调用**。
    这不是理论风险：第一版测试就是这么写的，结果 `test_no_proposals`
    读到了上一个测试留下的 3 条提案（`build_clean_ir` 明明返回 0 条）。
    """
    from tests.fixtures import clean_copy

    return clean_copy(Medium.NOVEL)


def _diff(did: str, status: DiffStatus) -> Diff:
    return Diff(
        id=did,
        target_card="chapter",
        field="goal",
        before="旧目标",
        after="新目标",
        rationale="AI 认为这里动机不足",
        source_card="biography",
        status=status,
    )


# ── A. 数据来源是 ir.proposals（持久化） ──────────────────────────


def test_empty() -> None:
    ir = _mk_ir()
    c = counts(ir)
    check("空 IR 各项为 0", c["total"] == 0 and c["decided"] == 0, str(c))
    check("空 IR 的 total 键完整",
          set(c) == {"accepted", "rejected", "conflicted", "pending",
                     "decided", "total"}, str(sorted(c)))


def test_counts_split() -> None:
    ir = _mk_ir()
    ir.proposals = [
        _diff("d1", DiffStatus.ACCEPTED),
        _diff("d2", DiffStatus.REJECTED),
        _diff("d3", DiffStatus.REJECTED),
        _diff("d4", DiffStatus.CONFLICTED),
        _diff("d5", DiffStatus.PENDING),
    ]
    c = counts(ir)
    check("accepted 正确", c["accepted"] == 1, str(c))
    check("rejected 正确", c["rejected"] == 2, str(c))
    check("conflicted 正确", c["conflicted"] == 1, str(c))
    check("pending 不进 decided", c["pending"] == 1, str(c))
    check("decided = 1+2+1 = 4", c["decided"] == 4, str(c))
    check("total = 4+1 = 5", c["total"] == 5, str(c))


def test_survives_json_roundtrip() -> None:
    """设计claim A：觉察必须跨会话成立，所以它读的是持久化的 proposals。

    内存态遥测（`DecisionTelemetry`）在进程结束后就没了；
    作者第二天回来接着写，看到的判断数必须还在。
    """
    ir = _mk_ir()
    ir.proposals = [
        _diff("d1", DiffStatus.ACCEPTED),
        _diff("d2", DiffStatus.REJECTED),
        _diff("d3", DiffStatus.PENDING),
    ]
    restored = NarrativeIR.from_json(ir.to_json())
    check("JSON 往返后 counts 不变",
          counts(restored) == counts(ir),
          f"{counts(restored)} != {counts(ir)}")
    check("JSON 往返后 awareness_line 不变",
          awareness_line(restored) == awareness_line(ir),
          awareness_line(restored))


# ── 措辞：三种状态各自说人话 ─────────────────────────────────────


def test_no_proposals() -> None:
    ir = _mk_ir()
    line = awareness_line(ir)
    check("无提案时不说『你做了 0 次判断』",
          "尚无" in line or "没有" in line, line)
    check("无提案时不输出『待你裁决 0 条』", "0 条" not in line, line)


def test_pending_only() -> None:
    ir = _mk_ir()
    ir.proposals = [_diff("d1", DiffStatus.PENDING),
                    _diff("d2", DiffStatus.PENDING)]
    line = awareness_line(ir)
    check("有待裁决时明确说『未做出判断』", "未" in line, line)
    check("待裁决条数正确", "2 条" in line, line)


def test_decided() -> None:
    ir = _mk_ir()
    ir.proposals = [
        _diff("d1", DiffStatus.ACCEPTED),
        _diff("d2", DiffStatus.REJECTED),
        _diff("d3", DiffStatus.REJECTED),
    ]
    line = awareness_line(ir)
    check("已判断 3 次", "3 次" in line, line)
    check("采纳 1 可见", "1" in line, line)
    check("驳回 2 可见", "2" in line, line)
    check("不再提示『未做出判断』", "未做出判断" not in line, line)


# ── B. 只报数、不评判 ────────────────────────────────────────────


def test_no_scoring() -> None:
    """设计claim B。

    「你的判断力 72 分」会把觉察又变成**一个可刷的指标**，
    那恰恰诱导 Reactive Writing（作者为了分数而裁决，不是为了故事）。
    """
    ir = _mk_ir()
    ir.proposals = [
        _diff("d1", DiffStatus.ACCEPTED),
        _diff("d2", DiffStatus.REJECTED),
    ]
    line = awareness_line(ir)
    check("不含百分号", "%" not in line, line)
    check("不含『分』（分数/评分）", "分" not in line, line)
    check("不含评级词",
          not any(w in line for w in ("优秀", "良好", "较差", "评级", "等级")),
          line)


def test_no_word_count() -> None:
    """设计claim C：判据是「你定了多少」，不是「AI 写了多少」。

    数生成字数会**鼓励** Reactive Writing —— 读建议、挑一个、看着字数涨。
    """
    ir = _mk_ir()
    ir.proposals = [_diff("d1", DiffStatus.ACCEPTED)]
    line = awareness_line(ir)
    check("不含字数/字数单位",
          not any(w in line for w in ("字", "tokens", "words")),
          line)


# ── scenes_touched：人工做过功的场景 ─────────────────────────────


def test_scenes_touched_origin() -> None:
    ir = _mk_ir()
    scenes = list(ir.scenes)
    if len(scenes) < 4:
        check("基线场景数不足，无法测本项", False, f"只有 {len(scenes)} 个场景")
        return
    # 先全部设为 AI 直出，再单独改 —— 否则基线里剩下的场景（默认 HUMAN）
    # 会被算进来，数出来的就不是我设的那几个。
    #
    # ⚠ 人造场景数必须**不对称**（这里是 2 : 4，不是 3 : 3）。
    # 第一版用了 3 个人工 + 3 个 AI 直出，结果把 `_HUMAN_WORK` 改成
    # `{AI_GENERATED}` 之后**仍然绿** —— 两边都是 3，断言等于没写。
    # 变异测试抓到的就是这个（见文件头变异表）。
    for s in scenes:
        s.origin = ChunkOrigin.AI_GENERATED

    scenes[0].origin = ChunkOrigin.HUMAN
    scenes[1].origin = ChunkOrigin.AI_ASSISTED
    check("HUMAN + AI_ASSISTED 计入（2 : 4 不对称）",
          scenes_touched(ir) == 2, f"得到 {scenes_touched(ir)}")

    # AI_EDITED 是「AI 生成 + 人工修改」—— 最该被看见的一类，单独验一次
    for s in scenes:
        s.origin = ChunkOrigin.AI_GENERATED
    scenes[0].origin = ChunkOrigin.AI_EDITED
    check("AI_EDITED 计入人工做功",
          scenes_touched(ir) == 1, f"得到 {scenes_touched(ir)}")


def test_scenes_touched_excludes_imported() -> None:
    ir = _mk_ir()
    for s in ir.scenes:
        s.origin = ChunkOrigin.IMPORTED
    check("IMPORTED 不算人工做功", scenes_touched(ir) == 0,
          f"得到 {scenes_touched(ir)}")


# ── awareness_block：必须解释「为什么给这个数」───────────────────


def test_block_explains_why() -> None:
    ir = _mk_ir()
    ir.proposals = [_diff("d1", DiffStatus.PENDING)]
    block = awareness_block(ir)
    check("block 至少 2 行", len(block) >= 2, str(len(block)))
    check("首行就是 line", block[0] == awareness_line(ir), block[0])
    joined = "\n".join(block)
    check("说明了来源（CHI 2026）", "CHI 2026" in joined, joined)
    check("说明了目的（可见 / 察觉）",
          "可见" in joined or "察觉" in joined, joined)


def test_block_warns_unjudged() -> None:
    ir = _mk_ir()
    ir.proposals = [_diff("d1", DiffStatus.PENDING)]
    joined = "\n".join(awareness_block(ir))
    check("未裁决时有提醒", "⚠" in joined and "裁决" in joined, joined)


def test_block_quiet_when_nothing() -> None:
    ir = _mk_ir()
    block = awareness_block(ir)
    check("无提案时 block 只有一行（不啰嗦）", len(block) == 1, str(len(block)))


# ── 集成：CriticLoop 真的会回显 ──────────────────────────────────


def test_criticloop_emits_awareness() -> None:
    """觉察必须发生在**写作时**，所以 CriticLoop 的 log 里必须有它。

    如果只在 `process-report` 里出现，本测试就会红 —— 那正是
    「申诉材料」与「过程觉察」的区别所在。
    """
    from loom.llm.mock import MockGenerator

    ir = _mk_ir()
    try:
        loop = CriticLoop(MockGenerator())
        _, log = loop.run(ir)
    except Exception as exc:  # 桩件在某些基线上可能抛错，本项只断言回显存在
        check("CriticLoop 回显觉察", False, f"异常：{exc}")
        return
    joined = "\n".join(log)
    check("CriticLoop log 含觉察回显",
          ("判断" in joined) or ("尚无结构提案" in joined),
          joined[:200])


def main() -> int:
    print("=" * 64)
    print("觉察回显（awareness）单元测试")
    print("=" * 64)
    for fn in (
        test_empty,
        test_counts_split,
        test_survives_json_roundtrip,
        test_no_proposals,
        test_pending_only,
        test_decided,
        test_no_scoring,
        test_no_word_count,
        test_scenes_touched_origin,
        test_scenes_touched_excludes_imported,
        test_block_explains_why,
        test_block_warns_unjudged,
        test_block_quiet_when_nothing,
        test_criticloop_emits_awareness,
    ):
        print(f"\n── {fn.__name__} ──")
        fn()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 64)
    print(f"结果：{passed}/{total} 项断言通过")
    print("=" * 64)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
