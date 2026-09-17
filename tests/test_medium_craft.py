"""媒介写作形态的单元测试（含变异测试）。

跑法：
    .venv/Scripts/python.exe tests/test_medium_craft.py

零依赖（不用 pytest），与 `tests/test_csn.py` / `test_rhythm.py` 同风格。

── 为什么需要这个文件 ─────────────────────────────────────────

起因是一起真实缺陷：选了「剧本」，产出的却是小说散文，只是被渲染器
套了一层场景标题。根因是 `prose` 提示词写死「你是小说作者」，
不感知媒介。修法分三处：

    ir/medium_craft.py   形态规格的**唯一定义**（跨层共用，仿 arcs.py）
    llm/prompts.py       prose 提示词注入形态规格
    llm/mock.py          桩件按媒介产出形态正确的正文

`scripts/verify.py` 第 3b 节做端到端的形态断言，本文件在**单元级**
把同样的判据钉死，并且做变异测试：把桩件改回「一律写小说散文」，
确认判据变红。没有这一步，「3b 节绿着」只说明它和当前实现一致，
不说明它测到了东西。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.ir.enums import Medium  # noqa: E402
from loom.ir.medium_craft import (  # noqa: E402
    MEDIUM_CRAFT,
    craft_brief,
    craft_for,
    length_hint,
    split_slugline,
)
from loom.llm import MockGenerator  # noqa: E402
from loom.pipeline import LoomPipeline  # noqa: E402

_IDEA = "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字"


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
# 1. 形态规格表
# ---------------------------------------------------------------------------


def test_table(t: T) -> None:
    print("\n── 1. 形态规格表 ──")
    missing = [m.value for m in Medium if m not in MEDIUM_CRAFT]
    t.ok(not missing, f"全部 {len(Medium)} 个媒介都有形态规格",
         f"缺：{missing}")

    empty = [
        m.value for m, c in MEDIUM_CRAFT.items()
        if not (c.form.strip() and c.bans.strip() and c.sample.strip())
    ]
    t.ok(not empty, "每条规格都有格式/禁止/样例三件套", f"不完整：{empty}")

    # 样例不是装饰：只给规则不给样例，模型照它对「剧本」的印象写，
    # 而不是照本项目的格式写 —— 而下游渲染器解析的是本项目的格式。
    t.ok(
        all(c.unit for c in MEDIUM_CRAFT.values()),
        "每条规格都声明了长度单位",
    )
    t.ok(
        all(c.words_per_unit > 0 for c in MEDIUM_CRAFT.values()),
        "长度换算系数均为正（否则会除以零）",
    )

    # 退化策略：未知/缺失一律走小说，不抛。
    t.eq(craft_for(None).medium, Medium.NOVEL, "缺失媒介退化为小说")
    t.eq(craft_for("bogus_value").medium, Medium.NOVEL, "未知媒介退化为小说")
    t.eq(craft_for("screenplay").label, "剧本", "按字符串也能取到规格")


# ---------------------------------------------------------------------------
# 2. 场景标题解析（内外景约定）
# ---------------------------------------------------------------------------


def test_slugline(t: T) -> None:
    print("\n── 2. 场景标题解析 ──")
    cases = [
        ("内景·书房", ("内景", "书房")),
        ("外景．码头", ("外景", "码头")),
        ("INT. STUDY", ("内景", "STUDY")),
        ("EXT. DOCK", ("外景", "DOCK")),
        ("书房", ("", "书房")),          # 没写内外景 = 不猜
        ("内外景·书房", ("内/外景", "书房")),
        ("", ("", "")),
        (None, ("", "")),
    ]
    for src, want in cases:
        t.eq(split_slugline(src), want, f"split_slugline({src!r})")


# ---------------------------------------------------------------------------
# 3. 长度提示
# ---------------------------------------------------------------------------


def test_length(t: T) -> None:
    print("\n── 3. 长度提示 ──")
    t.eq(length_hint(Medium.NOVEL, 800), "约 800 字。", "小说直接说字数")
    s = length_hint(Medium.SCREENPLAY, 800)
    t.ok("页" in s and "800" in s, f"剧本按页换算：{s}")
    t.ok("格" in length_hint(Medium.COMIC, 800), "漫画按格换算")
    t.ok("秒" in length_hint(Medium.MICRO_DRAMA, 800), "短剧按秒换算")
    t.eq(length_hint("bogus", 800), "约 800 字。", "未知媒介不换算")


# ---------------------------------------------------------------------------
# 4. 提示词注入
# ---------------------------------------------------------------------------


def test_brief(t: T) -> None:
    print("\n── 4. 提示词注入 ──")
    from loom.llm.base import REGISTRY

    p = REGISTRY.get("prose")
    t.ok("{medium_craft}" in p.template, "prose 模板注入了形态规格")
    t.ok("{length_hint}" in p.template, "prose 模板注入了长度提示")
    t.ok("小说" not in p.system[:20], "prose 系统提示不再写死「小说作者」",
         p.system[:40])

    brief = craft_brief(Medium.SCREENPLAY)
    t.ok("剧本" in brief and "对白" in brief, "剧本规格块含媒介名与对白要求")
    # 剧本必须显式禁止心理描写，否则不可拍摄
    t.ok("心理描写" in brief, "剧本规格块禁止心理描写")

    # 结构层要产出地点与时间：剧本场景标题没有第二处来源
    st = REGISTRY.get("structure")
    t.ok("location" in st.template, "structure 模板要求输出 location")
    t.ok("time_label" in st.template, "structure 模板要求输出 time_label")


# ---------------------------------------------------------------------------
# 5. 端到端形态 + 变异测试
# ---------------------------------------------------------------------------

#: 每个媒介的**形态标记**。与 verify.py 第 3b 节同一份判据，
#: 这里独立再写一遍是刻意的：那一节是端到端门禁，这一节要能
#: 在被改坏时**单独**变红，不能只靠那一节发现。
SHAPE_MARKS: dict[str, tuple[str, ...]] = {
    "screenplay": ("CUT TO:",),
    "micro_drama": ("？",),
    "comic": ("格 1｜画面：", "转场："),
    "interactive_fiction": ("* ",),
    "visual_novel": ("【立绘：", "「"),
    "murder_mystery": ("【第一幕", "【本幕任务】"),
}


def _bodies(patch: bool = False) -> dict[str, str]:
    """跑一遍流水线，返回 {媒介: 拼接正文}。

    patch=True 时注入变异：所有媒介退化成小说散文。
    """
    import loom.llm.mock as mock

    original = mock._prose_for_medium
    if patch:
        mock._prose_for_medium = (
            lambda payload, scene, rng: mock._prose_for(scene, rng)
        )
    try:
        out: dict[str, str] = {}
        for m in Medium:
            ir = LoomPipeline(MockGenerator()).run(
                _IDEA, medium=m, scene_count=2,
                words_per_scene=150, max_rounds=1,
            ).ir
            out[m.value] = "\n".join(
                (s.prose or "") for s in ir.ordered_scenes()
            )
        return out
    finally:
        mock._prose_for_medium = original


def test_shape(t: T) -> None:
    print("\n── 5. 端到端形态（含变异） ──")
    good = _bodies(patch=False)
    for name, marks in SHAPE_MARKS.items():
        body = good.get(name, "")
        missing = [mk for mk in marks if mk not in body]
        t.ok(bool(body.strip()) and not missing,
             f"{name} 的正文带本媒介形态标记",
             f"缺：{missing}；正文开头：{body[:60]!r}")

    # 小说/网文是散文体，没有可断言的形态标记 —— 强行造一个就是假门禁。
    t.ok("CUT TO:" not in good["novel"], "小说正文不出现剧本转场标记")

    print("\n  ── 变异：所有媒介退化成小说散文 ──")
    bad = _bodies(patch=True)
    caught = [
        name for name, marks in SHAPE_MARKS.items()
        if any(mk not in bad.get(name, "") for mk in marks)
    ]
    t.ok(
        len(caught) == len(SHAPE_MARKS),
        f"变异后形态判据全部变红（{len(caught)}/{len(SHAPE_MARKS)}）",
        f"没抓到的媒介：{[n for n in SHAPE_MARKS if n not in caught]}\n"
        "      → 判据是假门禁：实现坏成「一律写小说」它照样绿。",
    )


# ---------------------------------------------------------------------------


def main() -> int:
    t = T()
    print("═" * 64)
    print("  媒介写作形态 —— 规格表 / 场景标题 / 长度 / 提示词 / 端到端形态")
    print("═" * 64)
    test_table(t)
    test_slugline(t)
    test_length(t)
    test_brief(t)
    test_shape(t)

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
