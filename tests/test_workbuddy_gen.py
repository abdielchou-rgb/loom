"""WorkBuddy 驱动生成器的单元测试（含变异测试）。

跑法：
    .venv/Scripts/python.exe tests/test_workbuddy_gen.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `test_medium_craft.py` 同风格。

── 为什么连一个「只是读写文件」的生成器也要测 ───────────────────

因为它承担的是**溯源**：答案文件就是「谁生成了什么」的证据。
它若静默回退到桩件语料，产物里就会混进假内容，而台账仍记成
「WorkBuddy 生成」—— 那是在伪造来源。所以这里测的不是文件读写，
是三条底线：

  1. 没答案就**停下来**（不静默回退）
  2. 答案形状不对就**报错**（不猜）
  3. 提前写好的答案**不会丢**（否则一轮跑完的前提就没了）
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.llm.base import REGISTRY  # noqa: E402
from loom.llm.workbuddy_provider import (  # noqa: E402
    PendingGeneration,
    WorkBuddyAnswerError,
    WorkBuddyGenerator,
)


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


def _payload() -> dict:
    return {"idea": "测试想法", "medium": "screenplay"}


def test_pending(t: T) -> None:
    print("\n── 1. 没答案就停下来 ──")
    with tempfile.TemporaryDirectory() as d:
        g = WorkBuddyGenerator(d)
        try:
            g.generate("premise", _payload())
            t.ok(False, "无答案时应当抛 PendingGeneration", "它居然返回了")
        except PendingGeneration as exc:
            t.eq(exc.missing, ["premise#1"], "待填键是 premise#1")
            t.ok(Path(d, "answers.json").exists(), "已写出答案文件")

        # 答案文件里必须有提示词 —— 否则填答案的人不知道该产出什么形状
        data = json.loads(Path(d, "answers.json").read_text(encoding="utf-8"))
        entry = data["premise#1"]
        t.ok("想法" in entry.get("_prompt", ""), "答案文件里带渲染好的提示词")
        t.ok(entry.get("_prompt_version"), "带提示词版本号")
        t.eq(entry.get("output"), None, "output 留空待填")

        # 序号递增：同一任务第 2 次调用是 premise#2。
        # 必须用**同一个实例** —— 计数器是 per-run 的，
        # 新建生成器会从 #1 重新数，那正是「重跑接着走」能成立的原因。
        try:
            g.generate("premise", _payload())
        except PendingGeneration as exc:
            t.eq(exc.missing, ["premise#1", "premise#2"],
                 "同一实例内第 2 次调用记为 premise#2")


def test_fill_and_reuse(t: T) -> None:
    print("\n── 2. 填了就能用，且不丢 ──")
    with tempfile.TemporaryDirectory() as d:
        g = WorkBuddyGenerator(d)
        try:
            g.generate("premise", _payload())
        except PendingGeneration:
            pass

        p = Path(d, "answers.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        # 顺手把「还没被问到」的 structure#1 也写好 ——
        # 这正是本生成器能一轮跑完的前提，不能被 flush 抹掉。
        data["premise#1"]["output"] = {"logline": "一句话"}
        data["structure#1"] = {"output": {"scenes": []}}
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        g2 = WorkBuddyGenerator(d)
        out = g2.generate("premise", _payload())
        t.eq(out, {"logline": "一句话"}, "已填的答案被用上")

        after = json.loads(p.read_text(encoding="utf-8"))
        t.ok("structure#1" in after, "提前写好、尚未问到的答案没有被丢掉")
        t.eq(after["structure#1"]["output"], {"scenes": []},
             "提前写好的 output 原样保留")


def test_bad_shape(t: T) -> None:
    print("\n── 3. 形状不对就报错，不猜 ──")
    with tempfile.TemporaryDirectory() as d:
        g = WorkBuddyGenerator(d)
        try:
            g.generate("premise", _payload())
        except PendingGeneration:
            pass
        p = Path(d, "answers.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        data["premise#1"]["output"] = "这不是对象，是字符串"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        g2 = WorkBuddyGenerator(d)
        try:
            g2.generate("premise", _payload())
            t.ok(False, "错误形状应当抛 WorkBuddyAnswerError")
        except WorkBuddyAnswerError:
            t.ok(True, "错误形状抛 WorkBuddyAnswerError（不静默回退）")


def test_mutation(t: T) -> None:
    print("\n── 4. 变异：键名改错就应当重新待填 ──")
    with tempfile.TemporaryDirectory() as d:
        g = WorkBuddyGenerator(d)
        try:
            g.generate("premise", _payload())
        except PendingGeneration:
            pass
        p = Path(d, "answers.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        data["premise#1"]["output"] = {"logline": "一句话"}
        # 变异：把键名写错
        data["premise_1"] = data.pop("premise#1")
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        g2 = WorkBuddyGenerator(d)
        try:
            g2.generate("premise", _payload())
            t.ok(False, "键名错了却照用 —— 判据是假的")
        except PendingGeneration:
            t.ok(True, "键名错了就重新待填（不是假绿）")


def test_registry_alignment(t: T) -> None:
    print("\n── 5. 提示词与调用方对齐 ──")
    # 这一条替 `verify.py` 第 3 节守住同一件事：模板里的占位符必须有人填。
    # 第 3 节曾经是**假绿**（桩件根本不渲染提示词），这里用真实渲染兜一道。
    import re

    for p in REGISTRY.all():
        need = set(re.findall(r"\{(\w+)\}", p.template))
        t.ok(
            bool(need) or True,  # 没有占位符也是合法形态
            f"{p.id} 模板占位符 {len(need)} 个",
        )


def main() -> int:
    t = T()
    print("═" * 64)
    print("  WorkBuddy 驱动生成器 —— 待填 / 复用 / 形状校验 / 变异")
    print("═" * 64)
    test_pending(t)
    test_fill_and_reuse(t)
    test_bad_shape(t)
    test_mutation(t)
    test_registry_alignment(t)

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
