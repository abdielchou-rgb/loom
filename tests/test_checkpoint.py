"""自主运行检查点（`loom/pipeline/checkpoint.py`）的单元测试。

跑法：
    .venv/Scripts/python.exe tests/test_checkpoint.py

零依赖（不用 pytest），与 `tests/test_workbuddy_gen.py` / `test_drift.py` 同风格。
IR 全部在**本文件**里构造（不动 `tests/fixtures.py`）：共享 fixture 是集成方
串行编辑的文件，往里塞东西会与别人的改动互踩。

── 这个模块最容易「假绿」的三处，也是本文件的重心 ──────────────────

  1. **损坏被当成不存在。** `load()` 损坏文件返回 `None`，`load()` 没这个文件
     也返回 `None`。只断言「返回 None」的测试，在这两种截然不同的事实上
     长得一模一样 —— 判据等于没判。所以每条「返回 None」的断言都**必须**
     同时断言 `last_error.kind`，并且专门有一条把两种 kind 摆在一起对照。
  2. **原子写只是嘴上说说。** 断言「save 完文件是对的」证明不了原子性：
     非原子实现也能做到。真正的判据是**写一半崩了之后**，上一个好检查点
     还在不在。这里通过替换 `_serialize` 在写完临时文件后注入崩溃来测 ——
     见 `test_atomicity`，那是唯一能抓住「改成直接写目标文件」的用例。
  3. **续跑继承了别人的故事。** 不同 idea 必须开新档，且**不能**继承场景数、
     IR、台账。这条要是漏了，产出的是一篇「别人的第 47 场」长在自己身上
     的故事，而全链路没有任何一处会报错。
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.ir.enums import ArcShape, Medium, SceneOutcome  # noqa: E402
from loom.ir.models import (  # noqa: E402
    CommitmentLayer,
    NarrativeIR,
    SceneNode,
    TimePoint,
)
from loom.pipeline import checkpoint as cp  # noqa: E402

_IDEA_A = "一个校对员发现自己的批注正在改写现实"
_IDEA_B = "一位雪山的渡口守夜人清点旧账"


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"  ✓ {label}")
        else:
            self.failed.append(label)
            print(f"  ✗ {label}" + (f"\n      {detail}" if detail else ""))

    def eq(self, got, want, label: str) -> None:
        self.ok(got == want, label, f"期望 {want!r}，实际 {got!r}")


# ---------------------------------------------------------------------------
# 素材：IR 与 RunState
# ---------------------------------------------------------------------------


def _ir(n_scenes: int, *, prose: bool = True) -> NarrativeIR:
    return NarrativeIR(
        title="批注者",
        medium=Medium.NOVEL,
        commitment=CommitmentLayer(
            premise="过度纠错会摧毁被纠错之物",
            controlling_idea="交付信任才会被接住",
            logline="一个校对员必须停止修改世界",
            arc_shape=ArcShape.ICARUS,
            ending_anchor="他交出笔，世界留下一处错字",
        ),
        scenes=[
            SceneNode(
                id=f"s{i}",
                title=f"第 {i} 场",
                focalizer="c1",
                narrator="narrator",
                fabula_time=TimePoint(day=i),
                sjuzhet_index=i,
                value="信任",
                value_charge_start="-",
                value_charge_end="+",
                goal=f"他要确认第 {i} 处错字",
                conflict="纸面在抗拒",
                turning_point=f"第 {i} 次转折",
                outcome=SceneOutcome.YES_BUT,
                prose=(f"第 {i} 场的正文。" if prose else None),
            )
            for i in range(1, n_scenes + 1)
        ],
    )


def _state(
    *,
    run_id: str = "run-aaa",
    idea: str = _IDEA_A,
    scenes: int = 3,
    stamps: tuple[str, ...] = (),
) -> cp.RunState:
    return cp.RunState(
        run_id=run_id,
        idea=idea,
        params={"medium": "novel", "words": 1200, "scene_target": 12},
        completed_scenes=scenes,
        ir_json=_ir(scenes).to_json(),
        decisions=[{"ts": s, "proposal": "p", "verdict": "accepted"} for s in stamps],
        usage={"scenes": scenes, "tokens": 900 * scenes, "cost": 0.5 * scenes},
        updated_at="2026-09-14T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# 1. 往返
# ---------------------------------------------------------------------------


def test_roundtrip(t: T) -> None:
    print("\n── 1. save → load 往返 ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d) / "nested" / "runs"  # 目录不存在也应能建
        st = _state(scenes=3, stamps=("2026-09-14T01:00:00Z",))
        p = cp.save(st, directory)
        t.ok(p.exists(), "save 返回的路径存在（目录被自动创建）")
        t.eq(p.name, f"ckpt-{st.run_id}.json", "文件名由 run_id 决定，一 run 一文件")

        got = cp.load(p)
        t.ok(got is not None, "load 读回来了")
        t.eq(cp.last_error, None, "成功时 last_error 被清空（不留陈旧错误）")
        assert got is not None
        t.eq(got.run_id, st.run_id, "run_id 往返一致")
        t.eq(got.idea, st.idea, "idea 往返一致（含中文）")
        t.eq(got.params, st.params, "params 往返一致")
        t.eq(got.completed_scenes, 3, "completed_scenes 往返一致")
        t.eq(got.decisions, st.decisions, "决策台账往返一致")
        t.eq(got.usage, st.usage, "usage 往返一致")
        t.eq(got.ir_json, st.ir_json, "ir_json 逐字节往返一致")

        back = NarrativeIR.from_json(got.ir_json)
        t.eq(len(back.scenes), 3, "IR 由 ir_json 重建后场景数不变")
        t.eq(back.scenes[0].id, "s1", "重建后的场景 id 保留了顺序")
        t.eq(back.commitment.controlling_idea, "交付信任才会被接住",
             "重建后的控制理念没丢")


def test_timestamp_injection(t: T) -> None:
    print("\n── 2. 时间戳可注入（测试不 sleep 也确定）──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        st = _state()
        cp.save(st, directory, now="2026-09-14T10:00:00Z")
        t.eq(st.updated_at, "2026-09-14T10:00:00Z", "save 把注入的时刻盖到 state 上")
        cp.save(st, directory, now="2026-09-14T11:00:00Z")
        t.eq(cp.load(cp.save(st, directory, now="2026-09-14T11:00:00Z")).updated_at,
             "2026-09-14T11:00:00Z", "再次 save 覆盖同一文件（一 run 一文件）")

        # latest 按 updated_at 取最新，而不是靠 mtime 猜
        older = _state(run_id="run-old")
        cp.save(older, directory, now="2026-01-01T00:00:00Z")
        newest = cp.latest(directory)
        t.ok(newest is not None and newest.run_id == "run-aaa",
             "latest 取 updated_at 最新的那个",
             f"实际 {None if newest is None else newest.run_id}")


# ---------------------------------------------------------------------------
# 3. 续跑
# ---------------------------------------------------------------------------


def test_resume_same_idea(t: T) -> None:
    print("\n── 3. 同 idea 从第 N 场续上 ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        st = _state(run_id="run-aaa", idea=_IDEA_A, scenes=47,
                    stamps=("2026-09-14T01:00:00Z", "2026-09-14T02:00:00Z"))
        cp.save(st, directory, now="2026-09-14T02:00:00Z")

        got = cp.resume(directory, _IDEA_A, {"medium": "novel"})
        t.eq(got.run_id, "run-aaa", "续跑沿用同一个 run_id")
        t.eq(got.completed_scenes, 47, "completed_scenes 保住了 47（不是从 0 重来）")
        t.eq(len(got.decisions), 2, "决策台账一并续上")
        t.eq(got.usage["scenes"], 47, "usage 一并续上")
        ir = NarrativeIR.from_json(got.ir_json)
        t.eq(len(ir.scenes), 47, "IR 里的 47 场全部回来")
        t.eq(ir.scenes[46].title, "第 47 场", "第 47 场内容正确（不是被截断的旧版）")


def test_resume_other_idea_is_fresh(t: T) -> None:
    print("\n── 4. 换 idea 必须开新档，绝不继承 ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        cp.save(_state(run_id="run-aaa", idea=_IDEA_A, scenes=47),
                directory, now="2026-09-14T02:00:00Z")

        fresh = cp.resume(directory, _IDEA_B, {"medium": "screenplay"},
                          now="2026-09-14T03:00:00Z")
        t.eq(fresh.completed_scenes, 0, "新 idea 从第 0 场开始")
        t.eq(fresh.ir_json, "", "新 idea 不继承 IR（空串 = 尚无 IR）")
        t.eq(fresh.decisions, [], "新 idea 不继承别人的决策台账")
        t.eq(fresh.usage["scenes"], 0, "新 idea 不继承别人的用量")
        t.eq(fresh.idea, _IDEA_B, "新档记的是新想法")
        t.eq(fresh.params, {"medium": "screenplay"}, "新档用的是新参数")
        t.ok(fresh.run_id != "run-aaa", "run_id 与旧 run 不同",
             f"相同 run_id 会让两份文件互相覆盖：{fresh.run_id}")
        t.ok(fresh.run_id.startswith("run-"), "run_id 形状正常")

        # 旧 run 没有被新档碰坏 —— 换 idea 是「另起一份」，不是「改写」
        back = cp.latest(directory)
        t.ok(back is not None and back.run_id == "run-aaa",
             "开新档不影响磁盘上旧 run 的检查点",
             f"latest 现在是 {None if back is None else back.run_id}")


# ---------------------------------------------------------------------------
# 5. 损坏 vs 不存在（本模块的第一正确性）
# ---------------------------------------------------------------------------


def test_corrupt_is_not_absent(t: T) -> None:
    print("\n── 5. 截断的 JSON：不是异常，也不是「没有」──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        good = cp.save(_state(run_id="run-good"), directory, now="2026-09-14T01:00:00Z")
        payload = good.read_text(encoding="utf-8")

        # 5a. 截断成一半 —— 模拟写到一半断气
        half = good.parent / "ckpt-run-half.json"
        half.write_text(payload[: len(payload) // 2], encoding="utf-8")
        got = cp.load(half)  # 不许抛
        t.eq(got, None, "截断文件 load 返回 None（不抛异常）")
        t.ok(cp.last_error is not None, "但原因被记录在 last_error 上")
        assert cp.last_error is not None
        t.eq(cp.last_error.kind, "malformed", "kind 标明是「坏了」")
        t.ok(cp.last_error.path.endswith("ckpt-run-half.json"), "错误里带得是哪份文件")
        t.ok(not cp.last_error.is_absent, "is_absent 为 False：文件在，只是坏了")

        # 5b. 对照：真·不存在
        cp.load(good.parent / "ckpt-run-nope.json")
        assert cp.last_error is not None
        t.eq(cp.last_error.kind, "missing", "不存在 -> kind 是 missing")
        t.ok(cp.last_error.is_absent, "is_absent 为 True")

        # 5c. 两种「None」必须长得不一样，否则这条判据就是假的
        t.ok(cp.last_error.kind != "malformed",
             "「不存在」与「损坏」的 kind 不同 —— SKIPPED ≠ PASS")

        # 5d. 其它坏法也各有 kind，且都不抛
        cases = [
            ("ckpt-run-empty.json", "", "malformed"),
            ("ckpt-run-binary.json", "\x00\x01\x02", "malformed"),
            ("ckpt-run-list.json", "[]", "schema"),
            ("ckpt-run-nofmt.json", '{"run_id": "x"}', "version"),
        ]
        for name, text, want in cases:
            p = good.parent / name
            p.write_text(text, encoding="utf-8")
            t.eq(cp.load(p), None, f"{name} 返回 None 且不抛")
            assert cp.last_error is not None
            t.eq(cp.last_error.kind, want, f"{name} 的 kind 是 {want}")

        # 5e. 缺字段 / 类型不对
        p = good.parent / "ckpt-run-partial.json"
        p.write_text(json.dumps({"_format": 1, "run_id": "x"}), encoding="utf-8")
        t.eq(cp.load(p), None, "缺字段返回 None")
        assert cp.last_error is not None
        t.eq(cp.last_error.kind, "schema", "缺字段 -> schema")


def test_latest_reports_corruption(t: T) -> None:
    print("\n── 6. latest：拿到好的，但不吞掉坏的 ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        cp.save(_state(run_id="run-good"), directory, now="2026-09-14T05:00:00Z")
        (directory / "ckpt-run-bad.json").write_text('{"_format": 1, "run_i', encoding="utf-8")

        got = cp.latest(directory)
        t.ok(got is not None and got.run_id == "run-good",
             "有一个坏文件时不耽误用好的那个",
             f"实际 {None if got is None else got.run_id}")
        t.ok(cp.last_error is not None, "但 last_error 仍然被置上（坏消息不消失）")
        assert cp.last_error is not None
        t.eq(cp.last_error.kind, "malformed", "last_error 说的是那个坏文件")

        # 全是坏的：None + 非空 last_error（不是「没有检查点」）
        cp.clear(directory)
        (directory / "ckpt-run-bad2.json").write_text("{", encoding="utf-8")
        t.eq(cp.latest(directory), None, "全是坏文件时 latest 返回 None")
        t.ok(cp.last_error is not None and cp.last_error.kind == "malformed",
             "此时 last_error 是 malformed 而不是 missing")

        # resume 在坏文件面前不开新档 —— 悄悄从 0 重来会把「丢了 N 场」藏掉
        try:
            cp.resume(directory, _IDEA_A, {})
            t.ok(False, "有损坏检查点时 resume 应当抛 CorruptCheckpointError")
        except cp.CorruptCheckpointError as exc:
            t.ok(True, "resume 抛 CorruptCheckpointError（不静默重来）")
            t.eq(exc.error.kind, "malformed", "异常里带着损坏原因")


# ---------------------------------------------------------------------------
# 7. 原子性（唯一能抓住「改成直接写目标文件」的用例）
# ---------------------------------------------------------------------------


def test_atomicity(t: T) -> None:
    print("\n── 7. 写一半崩了，上一个好检查点必须还在 ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        st = _state(run_id="run-aaa", scenes=47)
        final = cp.save(st, directory, now="2026-09-14T01:00:00Z")

        # 注入崩溃：临时文件已经开了、内容还没落盘就炸。
        # 原子实现 -> final 仍是上一版完整内容；直接写 final -> final 变半截。
        real_serialize = cp._serialize
        try:
            def boom(_state: cp.RunState) -> str:
                raise RuntimeError("模拟：序列化后、replace 前崩了")

            cp._serialize = boom  # type: ignore[assignment]
            try:
                cp.save(st, directory, now="2026-09-14T02:00:00Z")
                t.ok(False, "save 应当把异常抛出来")
            except RuntimeError:
                t.ok(True, "崩溃时异常照常上抛（没有被吞）")
        finally:
            cp._serialize = real_serialize  # type: ignore[assignment]

        t.ok(final.exists(), "崩溃后目标文件仍在")
        t.eq(cp.last_error, None, "崩溃没有污染 last_error")
        survived = cp.load(final)
        t.ok(survived is not None, "上一个好检查点**原封不动**地活着")
        assert survived is not None
        t.eq(survived.completed_scenes, 47, "活着的那版还是第 47 场")
        t.eq(survived.updated_at, "2026-09-14T01:00:00Z", "没有被半成品把时间戳改掉")
        t.eq(len(NarrativeIR.from_json(survived.ir_json).scenes), 47, "IR 完好")

        leftovers = list(directory.glob("*.tmp"))
        t.ok(not leftovers, "崩溃后没有留下临时文件垃圾", f"残留 {leftovers}")

        # 光「崩完还有旧档」证明不了原子性 —— 直接写目标文件的实现，只要
        # 崩在动笔之前也一样过。所以还要盯住 `os.replace` 那一刻：
        # 换上去的东西必须是**完整**的，且换之前目标文件仍是**旧**的。
        # 直接写目标文件的实现在这里必然露馅（要么没调 replace，
        # 要么调的时候目标已经被写成新的了）。
        old_text = final.read_text(encoding="utf-8")
        expected = real_serialize(replace(st, updated_at="2026-09-14T03:00:00Z"))
        seen: dict[str, object] = {}
        real_replace = cp.os.replace

        def spy(src, dst, **kw):
            src_p, dst_p = Path(src), Path(dst)
            seen["src_suffix"] = src_p.suffix
            seen["src_complete"] = src_p.read_text(encoding="utf-8") == expected
            seen["dst_untouched"] = dst_p.read_text(encoding="utf-8") == old_text
            return real_replace(src, dst, **kw)

        cp.os.replace = spy  # type: ignore[assignment]
        try:
            cp.save(st, directory, now="2026-09-14T03:00:00Z")
        finally:
            cp.os.replace = real_replace  # type: ignore[assignment]

        t.eq(seen.get("src_suffix"), ".tmp", "换上去的是临时文件（不是直接写目标）")
        t.eq(seen.get("src_complete"), True, "换上去时内容已经写完整（不是半截）")
        t.eq(seen.get("dst_untouched"), True,
             "replace 之前目标文件仍是上一版完整内容 —— 读者永远看不到半截")
        t.eq(json.loads(final.read_text(encoding="utf-8"))["updated_at"],
             "2026-09-14T03:00:00Z", "换完之后是新内容")

        # 另半边：如果有人绕过原子写、直接把半截内容写进目标文件，
        # 那必须被识别成「损坏」，而不是被读成一个第 0 场的空档。
        final.write_text('{"_format": 1, "run_id": "run-aaa", "completed_', encoding="utf-8")
        t.eq(cp.load(final), None, "半截内容不会被读成一个合法状态")
        t.ok(cp.last_error is not None and cp.last_error.kind == "malformed",
             "半截内容被判为损坏")


# ---------------------------------------------------------------------------
# 8. clear
# ---------------------------------------------------------------------------


def test_clear(t: T) -> None:
    print("\n── 8. clear ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        cp.save(_state(run_id="run-a"), directory, now="2026-09-14T01:00:00Z")
        cp.save(_state(run_id="run-b"), directory, now="2026-09-14T02:00:00Z")
        (directory / "ckpt-run-c.tmp").write_text("写了一半", encoding="utf-8")
        t.ok(len(list(directory.glob("ckpt-*"))) == 3, "先有 3 个文件（含临时）")

        cp.clear(directory)
        t.eq(list(directory.glob("ckpt-*.json")), [], "检查点被清空")
        t.eq(list(directory.glob("*.tmp")), [], "残留临时文件一并清掉")
        t.eq(cp.latest(directory), None, "clear 之后 latest 为空")
        t.ok(cp.last_error is not None and cp.last_error.kind == "missing",
             "此时是「没有」，不是「坏了」")

        cp.clear(directory)  # 幂等
        cp.clear(Path(d) / "不存在的目录")  # 目录不存在也不许炸
        t.ok(True, "clear 幂等，且对不存在的目录不报错")

        # 清干净之后能正常开新档
        fresh = cp.resume(directory, _IDEA_A, {"medium": "novel"})
        t.eq(fresh.completed_scenes, 0, "清空后可正常开新档")


# ---------------------------------------------------------------------------
# 9. 变异：文件内数据被改坏
# ---------------------------------------------------------------------------


def test_mutation_of_identity(t: T) -> None:
    print("\n── 9. 变异：把 idea 改掉就不该被续上 ──")
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        p = cp.save(_state(run_id="run-aaa", scenes=47), directory,
                    now="2026-09-14T01:00:00Z")
        data = json.loads(p.read_text(encoding="utf-8"))
        data["idea"] = _IDEA_B  # 变异：检查点被标成另一个想法
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        got = cp.resume(directory, _IDEA_A, {})
        t.eq(got.completed_scenes, 0,
             "idea 对不上就不续 —— 否则就是在用别人的第 47 场")


def main() -> int:
    t = T()
    print("═" * 64)
    print("  自主运行检查点 —— 往返 / 续跑 / 损坏≠不存在 / 原子写 / clear")
    print("═" * 64)
    test_roundtrip(t)
    test_timestamp_injection(t)
    test_resume_same_idea(t)
    test_resume_other_idea_is_fresh(t)
    test_corrupt_is_not_absent(t)
    test_latest_reports_corruption(t)
    test_atomicity(t)
    test_clear(t)
    test_mutation_of_identity(t)

    print("\n" + "─" * 64)
    print(f"  通过 {t.passed} · 失败 {len(t.failed)}")
    if t.failed:
        for f in t.failed:
            print(f"    ✗ {f}")
        return 1
    print("  全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
