"""CSN 数值事实一致性 —— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**，期望值全部从
汉语语法与需求推导，不是从实现里抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_csn.py

零依赖（不用 pytest），与本项目其余部分一致。

── 为什么这个模块值得存在 ──────────────────────────────

跨章数值矛盾是网文读者最能一眼抓到的「吃书」形态：
第 3 章「他修了十一年」，第 40 章变成「十二年」。这类矛盾**纯规则可判**，
不需要任何语义理解，因此是性价比最高的一致性门禁 —— 前提是抽取足够保守。

抽取的最大风险不是漏，是**误报**：把「青山局的编制有三百人」抽成
「青山 = 300 人」，就会在正常文本上乱报警。所以下面的测试里，
「不该抽出来」的用例比「该抽出来」的还多。

── 期望值的来源 ────────────────────────────────────────

数词规则来自汉语本身的构词法（万以下：数词 × 单位 逐段相加），
不是任何项目的词表：
    十一 = 10 + 1 = 11        二十一 = 2×10 + 1 = 21
    一百零五 = 100 + 5 = 105   两千三百 = 2×1000 + 3×100 = 2300
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 极简断言框架（与 scripts/verify.py 同风格，不引入 pytest）
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
# 1. 中文数词归一化
# ---------------------------------------------------------------------------


def test_normalize(t: T) -> None:
    from loom.audit.csn import normalize_cn_number as N

    t.group("1. 中文数词归一化")
    cases: list[tuple[str, int | None]] = [
        # -- 单位以下 --
        ("零", 0),
        ("〇", 0),
        ("一", 1),
        ("两", 2),
        ("九", 9),
        # -- 十位 --
        ("十", 10),          # 「十」单独出现 = 10（汉语省略前导「一」）
        ("十一", 11),
        ("二十", 20),
        ("二十一", 21),
        ("三十", 30),
        ("九十九", 99),
        # -- 百千 --
        ("一百", 100),
        ("百", 100),
        ("一百零五", 105),   # 「零」占位，不参与求和
        ("两百", 200),
        ("三百六十", 360),
        ("一千", 1000),
        ("两千三百", 2300),
        # -- 阿拉伯数字直通 --
        ("21", 21),
        ("300", 300),
        # -- 非数词必须返回 None（不是 0！0 与「无法解析」必须可区分）--
        ("", None),
        ("他", None),
        ("abc", None),
        ("十年", None),      # 带单位 → 不是纯数词
        ("十一年", None),    # 同上
        ("负一", None),
        ("3.5", None),       # 小数不在本模块范围内
    ]
    for src, want in cases:
        t.eq(N(src), want, f"normalize({src!r})")


# ---------------------------------------------------------------------------
# 2. 数值事实抽取
# ---------------------------------------------------------------------------


def test_scan(t: T) -> None:
    from loom.audit.csn import scan_numeric_facts

    t.group("2. 数值事实抽取（该抽出来的）")
    names = {"陈默", "沈砚"}

    facts = scan_numeric_facts("陈默修了十一年罪忆水晶。", names=names, scene_id="sc1")
    t.eq(len(facts), 1, "抽出一条事实")
    if facts:
        f = facts[0]
        t.eq(f.subject, "陈默", "主体")
        t.eq(f.predicate, "修", "谓语（剥掉体标记「了」）")
        t.eq(f.value, 11, "数值 十一年 → 11")
        t.eq(f.unit, "年", "单位")
        t.eq(f.scene_id, "sc1", "场次")

    facts = scan_numeric_facts("沈砚在崖下等了三十年。", names=names, scene_id="sc1")
    t.eq(len(facts), 1, "抽出一条事实（等了三十年）")
    if facts:
        t.eq(facts[0].value, 30, "三十年 → 30")
        t.eq(facts[0].predicate, "等", "谓语（剥掉体标记「了」）")

    facts = scan_numeric_facts("陈默当了二十一载皇帝。", names=names, scene_id="sc1")
    t.ok(all(f.value != 21 for f in facts), "「载」不是受支持的单位 → 不抽")

    # 长状语：真实行文里谓语前面常带方位短语，间隔会超过 6 字
    # （这条是实战发现的：单元测试原本只用了「在崖下等了」这种短状语，
    #   于是「在那座塔下守了」被漏掉，而漏掉的正是本模块的主用例）
    facts = scan_numeric_facts(
        "沈砚在那座塔下守了十一年。", names=names, scene_id="sc1"
    )
    t.eq(len(facts), 1, "长状语「在那座塔下守了」→ 仍应抽出")
    if facts:
        t.eq(facts[0].value, 11, "长状语：数值 11")
        t.eq(facts[0].predicate, "守", "长状语：谓语取末字「守」")

    facts = scan_numeric_facts(
        "沈砚已经在那里默默守了三十年。", names=names, scene_id="sc1"
    )
    t.eq(len(facts), 1, "长状语（副词叠加）→ 仍应抽出")

    # 同一句里两个主体各一条
    facts = scan_numeric_facts(
        "陈默活了三十年，沈砚只活了二十五年。", names=names, scene_id="sc1"
    )
    t.eq(len(facts), 2, "一句两条事实")
    t.eq(sorted(f.value for f in facts), [25, 30], "两条数值各自正确")

    t.group("3. 误报抑制（不该抽出来的）")

    # 的-修饰主体：「陈默的刀」的数值属于刀，不属于陈默
    facts = scan_numeric_facts("陈默的刀有三十斤重。", names=names, scene_id="sc1")
    t.eq(facts, [], "「X 的 Y」中 X 是修饰语 → 不抽")

    # 机构后缀：名字只是机构名的一部分
    facts = scan_numeric_facts(
        "青山局有三百人。", names={"青山"}, scene_id="sc1"
    )
    t.eq(facts, [], "名字后接机构后缀（局）→ 不抽")

    # 地名后缀：名字只是地名的一部分
    # （用「人」而不是「户」——「户」不在受支持单位里，那样写就测不到这条守卫）
    facts = scan_numeric_facts(
        "临阳城有三千人。", names={"临阳"}, scene_id="sc1"
    )
    t.eq(facts, [], "名字后接地名后缀（城）→ 不抽")

    # 代词主体：无法跨章稳定对齐，抽了只会制造噪声
    facts = scan_numeric_facts("他等了三十年。", names=names, scene_id="sc1")
    t.eq(facts, [], "代词主体 → 不抽")

    # 间隔里出现**另一个**具名角色 → 动作属于离数词最近的那个人。
    # 放宽间隔上限后，这是最主要的误报来源：「沈砚说陈默守了十一年」
    # 若把主体记成沈砚，就会凭空造出一条沈砚的事实。
    facts = scan_numeric_facts(
        "沈砚看着陈默在塔下守了十一年。", names=names, scene_id="sc1"
    )
    t.eq(len(facts), 1, "间隔里有另一个具名角色 → 抽 1 条")
    if facts:
        t.eq(facts[0].subject, "陈默", "主体归给离数词最近的那个人，不是句首那个")

    facts = scan_numeric_facts(
        "沈砚说陈默守了十一年。", names=names, scene_id="sc1"
    )
    t.eq(len(facts), 1, "「A 说 B 守了 N 年」→ 抽 1 条")
    if facts:
        t.eq(facts[0].subject, "陈默", "「A 说 B…」的主体是 B，不是 A")

    # 未登记的名字
    facts = scan_numeric_facts("张三等了三十年。", names=names, scene_id="sc1")
    t.eq(facts, [], "未登记的名字 → 不抽")

    # 标点必须切断主体与数值的关联
    facts = scan_numeric_facts(
        "陈默抬头。十一年前的事。", names=names, scene_id="sc1"
    )
    t.eq(facts, [], "句号切断 → 不抽")

    # 空文本
    t.eq(scan_numeric_facts("", names=names, scene_id="sc1"), [], "空文本 → 无事实")


# ---------------------------------------------------------------------------
# 4. 冲突检测
# ---------------------------------------------------------------------------


def test_conflicts(t: T) -> None:
    from loom.audit.csn import find_conflicts, scan_numeric_facts

    t.group("4. 跨场冲突检测")
    names = {"陈默", "沈砚"}

    def scan(text: str, sid: str):
        return scan_numeric_facts(text, names=names, scene_id=sid)

    # 跨场矛盾：同一主体 + 同一谓语 + 同一单位，数值不同
    facts = scan("陈默修了十一年。", "sc1") + scan("陈默修了十二年。", "sc5")
    conflicts = find_conflicts(facts)
    t.eq(len(conflicts), 1, "跨场数值矛盾 → 1 条")
    if conflicts:
        c = conflicts[0]
        t.eq(c.subject, "陈默", "冲突主体")
        t.eq(c.unit, "年", "冲突单位")
        t.eq(sorted(c.values), [11, 12], "冲突数值集合")
        t.eq(sorted(c.scenes), ["sc1", "sc5"], "涉及场次")

    # 同值复述不是矛盾
    facts = scan("陈默修了十一年。", "sc1") + scan("陈默修了十一年。", "sc5")
    t.eq(find_conflicts(facts), [], "同值复述 → 无冲突")

    # 不同单位不矛盾（活了三十年 vs 走了三千里）
    facts = scan("陈默等了三十年。", "sc1") + scan("陈默走了三千里。", "sc5")
    t.eq(find_conflicts(facts), [], "不同谓语/单位 → 不混为一谈")

    # 不同主体不矛盾
    facts = scan("陈默等了三十年。", "sc1") + scan("沈砚等了四十年。", "sc5")
    t.eq(find_conflicts(facts), [], "不同主体 → 不矛盾")

    # 同一场内自相矛盾
    # （必须重复具名主体 —— 换成代词「他」就抽不出来，那正是上一条守卫的代价）
    facts = scan("陈默等了三十年，后来陈默等了四十年。", "sc1")
    conflicts = find_conflicts(facts)
    t.eq(len(conflicts), 1, "同场内部矛盾 → 1 条")

    # 空输入
    t.eq(find_conflicts([]), [], "无事实 → 无冲突")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  CSN 数值事实一致性 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_normalize(t)
        test_scan(t)
        test_conflicts(t)
    except ImportError as exc:
        print(f"\n  ✗ 模块尚不存在（RED 阶段预期如此）：{exc}")
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
