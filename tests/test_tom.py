"""理论心智（ToM）信念层与张力生成 —— 测试先行。

按 TDD 纪律写：**这些断言在实现存在之前就写好了**，期望值从
`aesirian_吸收评估.md` ② 的设计约束推导，不是从实现里抄回来的。

跑法：
    .venv/Scripts/python.exe tests/test_tom.py

零依赖（不用 pytest），与 `tests/test_csn.py` 同风格。

── 这个模块唯一值得存在的能力 ──────────────────────────

Loom 现有 24 个校验器**全部是向后看的**：你写错了什么。
ToM 层是第一个**向前看的**结构：你接下来可以写什么。

所以本测试的核心不是「检测到了一条张力」（那只是一个布尔），而是
**「张力点带走了可执行的下一步」** —— 第 5 组专门断言每个张力点的
`suggestion` 非空，并断言 schema 层面**不允许**构造出没有建议的张力点。
一个只报「这里有信念冲突」而不说「下一场怎么用」的模块，等于把
enigma ledger 又做了一遍。

── 第 2 组是本文件的地基 ────────────────────────────────

戏剧反讽的判据是**真值与信念不一致**。测试必须证明它
「不一致就报、一致就不报」——只测前者的话，一个 `return 全部信念`
的恒真实现也能通过。所以第 2 组里「一致 → 空」的断言与
「不一致 → 一条」的断言同等重要。

── 期望值的来源 ────────────────────────────────────────

强度先验取自 `aesirian_吸收评估.md` ② 的明文规定：
    递归错位  0.9（最高）   戏剧反讽  0.8（固定）
    信念冲突  两者置信度均值
其余三类（秘密暴露风险 0.7 / 目标冲突 0.6）是本模块自定的先验，
不是从文献读出来的系数 —— 第 3 组测的是**排序关系**，不是数值科不科学。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def raises(fn) -> bool:
    """执行 fn，抛任何异常即视为 True。用于断言 schema 的硬约束。"""
    try:
        fn()
    except Exception:
        return True
    return False


# ---------------------------------------------------------------------------
# 构造工具 —— 只填本模块真正读取的字段
# ---------------------------------------------------------------------------


def _b(prop: str, value, conf: float = 1.0, src=None):
    from loom.ir.tom import Belief, BeliefSource

    return Belief(
        proposition=prop,
        value=value,
        confidence=conf,
        source=src or BeliefSource.WITNESSED,
    )


def _s(**kw):
    from loom.ir.tom import CharacterBeliefState

    return CharacterBeliefState(**kw)


# ---------------------------------------------------------------------------
# 1. Belief / BeliefSource
# ---------------------------------------------------------------------------


def test_belief_model(t: T) -> None:
    from loom.ir.tom import Belief, BeliefSource

    t.group("1. Belief / BeliefSource")

    t.eq(BeliefSource.WITNESSED.value, "目击", "来源·目击")
    t.eq(BeliefSource.HEARSAY.value, "二手信息", "来源·二手信息")
    t.eq(BeliefSource.INFERENCE.value, "推理", "来源·推理")
    t.eq(BeliefSource.DECEPTION.value, "欺骗", "来源·欺骗")
    t.eq(BeliefSource.MISUNDERSTANDING.value, "误解", "来源·误解")

    # 后两者是「错误信念」的来源，必须自动派生 is_erroneous，
    # 不能靠调用方记得手填（忘了填就会让反讽检测漏掉整类信念）
    for src in (BeliefSource.DECEPTION, BeliefSource.MISUNDERSTANDING):
        b = Belief(proposition="门是锁的", value="开着的", confidence=0.9, source=src)
        t.ok(b.is_erroneous, f"{src.value} → is_erroneous 自动为真")
    for src in (BeliefSource.WITNESSED, BeliefSource.HEARSAY, BeliefSource.INFERENCE):
        b = Belief(proposition="门是锁的", value="锁着的", confidence=0.9, source=src)
        t.ok(not b.is_erroneous, f"{src.value} → 非错误信念")

    t.ok(
        raises(lambda: Belief(proposition="p", value=1, confidance=0.5)),
        "未知字段被拒绝（extra=forbid）",
    )
    t.ok(
        raises(lambda: Belief(proposition="p", value=1, confidence=1.5)),
        "confidence > 1 被拒绝",
    )
    t.ok(
        raises(lambda: Belief(proposition="p", value=1, confidence=-0.1)),
        "confidence < 0 被拒绝",
    )


# ---------------------------------------------------------------------------
# 2. 【核心】戏剧反讽：真值 vs 信念
# ---------------------------------------------------------------------------


def test_dramatic_irony(t: T) -> None:
    from loom.ir.tom import TensionType, find_dramatic_irony

    t.group("2. 【核心】戏剧反讽：只有真值与信念不一致才成立")

    truth = {"沈砚已死": "已死"}

    # --- 不一致 → 一条反讽点 ---
    disagree = {
        "陈默": _s(
            world_beliefs={
                "沈砚已死": _b("沈砚已死", "活着", 0.9, _src("MISUNDERSTANDING"))
            }
        )
    }
    pts = find_dramatic_irony(disagree, truth)
    t.eq(len(pts), 1, "读者知道真相、角色信错 → 产出 1 条反讽点")
    if pts:
        p = pts[0]
        t.eq(p.type, TensionType.DRAMATIC_IRONY, "张力类型")
        t.eq(p.involved, ["陈默"], "涉及角色")
        t.eq(p.intensity, 0.8, "戏剧反讽强度固定 0.8")
        t.ok("陈默" in p.description, "描述里点名角色")
        t.ok("已死" in p.description, "描述里点出客观真相")
        t.ok(p.suggestion.strip(), "必须带下一步建议")

    # --- 一致 → 零条（这条与上一条同等重要：恒真实现必须在这里死掉）---
    agree = {
        "陈默": _s(world_beliefs={"沈砚已死": _b("沈砚已死", "已死", 0.9)})
    }
    t.eq(find_dramatic_irony(agree, truth), [], "真值与信念一致 → 不报反讽")

    # --- 真值层没有该命题 → 无从比对，保守不报 ---
    unknown = {
        "陈默": _s(world_beliefs={"钥匙在井底": _b("钥匙在井底", "在井底")})
    }
    t.eq(find_dramatic_irony(unknown, truth), [], "真值层缺该命题 → 不臆测反讽")

    # --- 置信度不参与判定：信得再虚，错就是错 ---
    faint = {
        "陈默": _s(world_beliefs={"沈砚已死": _b("沈砚已死", "活着", 0.05)})
    }
    t.eq(len(find_dramatic_irony(faint, truth)), 1, "低置信度的错误信念同样是反讽")

    # --- 两个角色同时信错 → 两条，且各自点名 ---
    both = {
        "陈默": _s(world_beliefs={"沈砚已死": _b("沈砚已死", "活着", 0.9)}),
        "林砚": _s(world_beliefs={"沈砚已死": _b("沈砚已死", "重伤", 0.9)}),
    }
    pts = find_dramatic_irony(both, truth)
    t.eq(len(pts), 2, "两个角色都信错 → 两条反讽点")
    t.eq(sorted(p.involved[0] for p in pts), ["林砚", "陈默"], "两条各自归属正确")

    # --- 空输入 ---
    t.eq(find_dramatic_irony({}, {}), [], "空输入 → 无反讽点")


def _src(name: str):
    from loom.ir.tom import BeliefSource

    return getattr(BeliefSource, name)


# ---------------------------------------------------------------------------
# 3. 【核心】强度序：递归错位 > 戏剧反讽 > 信念冲突
# ---------------------------------------------------------------------------


def _scenario():
    """一个同时具备五种张力的最小世界。

    陈默：信「沈砚已死」为「活着」（反讽 0.8）；以为沈砚知道「沈砚已死」
          （沈砚实际不知 → 递归错位 0.9）；藏秘密「陈默是卧底」。
    沈砚：信「城墙会塌」为「不会」，与陈默的「会」相冲（冲突 = (0.6+0.8)/2 = 0.7）；
          已信「陈默是卧底」为真（秘密暴露 0.7）。
    两人都追「夺回钥匙」（目标冲突 0.6）。
    """
    truth = {"沈砚已死": "已死", "陈默是卧底": "是卧底"}
    a = _s(
        world_beliefs={
            "沈砚已死": _b("沈砚已死", "活着", 0.9, _src("MISUNDERSTANDING")),
            "城墙会塌": _b("城墙会塌", "会", 0.6, _src("INFERENCE")),
        },
        recursive_beliefs={
            "沈砚": {"沈砚": {"沈砚已死": _b("沈砚已死", "已死", 0.8, _src("INFERENCE"))}}
        },
        known_secrets=["陈默是卧底"],
        active_goals=["夺回钥匙"],
    )
    b = _s(
        world_beliefs={
            "城墙会塌": _b("城墙会塌", "不会", 0.8, _src("INFERENCE")),
            "陈默是卧底": _b("陈默是卧底", "是卧底", 0.6, _src("INFERENCE")),
        },
        active_goals=["夺回钥匙"],
    )
    return {"陈默": a, "沈砚": b}, truth


def test_intensity_ordering(t: T) -> None:
    from loom.ir.tom import TensionType, derive_tension_points

    t.group("3. 【核心】强度序（递归错位 > 戏剧反讽 > 信念冲突）")

    states, truth = _scenario()
    pts = derive_tension_points(states, truth)

    t.eq(len(pts), 5, "恰好五条张力点，不多不少（无虚假报警）")
    t.eq(
        sorted(p.type.value for p in pts),
        sorted(["信念冲突", "戏剧反讽", "递归错位", "秘密暴露风险", "目标冲突"]),
        "五种类型齐备",
    )

    rec = [p for p in pts if p.type is TensionType.RECURSIVE_MISMATCH]
    irony = [p for p in pts if p.type is TensionType.DRAMATIC_IRONY]
    conf = [p for p in pts if p.type is TensionType.BELIEF_CONFLICT]
    t.ok(rec and irony and conf, "三类关键张力都存在")

    t.eq(rec[0].intensity, 0.9, "递归错位 = 0.9（最高）")
    t.eq(irony[0].intensity, 0.8, "戏剧反讽 = 0.8（固定）")
    t.eq(conf[0].intensity, 0.7, "信念冲突 = (0.6+0.8)/2 = 0.7（置信度均值）")
    t.ok(
        rec[0].intensity > irony[0].intensity > conf[0].intensity,
        "强度序 0.9 > 0.8 > 0.7",
    )

    # 输出必须已按强度降序排好 —— 消费方（TensionSeeder）不该自己再排一次
    t.eq(
        [p.intensity for p in pts],
        [0.9, 0.8, 0.7, 0.7, 0.6],
        "整体按强度降序",
    )
    t.eq(pts[0].type, TensionType.RECURSIVE_MISMATCH, "最高强度的是递归错位")
    t.eq(pts[0].involved, ["陈默", "沈砚"], "递归错位涉及 A 与 A 眼中的 B")


# ---------------------------------------------------------------------------
# 4. 五种张力各自的判据
# ---------------------------------------------------------------------------


def test_recursive_mismatch(t: T) -> None:
    from loom.ir.tom import TensionType, derive_tension_points

    t.group("4a. 递归错位：A 以为 B 相信 X，B 其实不")

    # A 以为 B 知道「沈砚已死」，B 的 world_beliefs 里根本没有这条
    states = {
        "陈默": _s(
            recursive_beliefs={"沈砚": {"沈砚": {"沈砚已死": _b("沈砚已死", "已死", 0.8)}}}
        ),
        "沈砚": _s(),
    }
    pts = [p for p in derive_tension_points(states, {}) if p.type is TensionType.RECURSIVE_MISMATCH]
    t.eq(len(pts), 1, "A 以为 B 知道、B 其实不知道 → 1 条")
    t.ok(pts and pts[0].suggestion.strip(), "递归错位必须带建议")

    # A 对 B 的建模与 B 的实际信念一致 → 不报
    agree = {
        "陈默": _s(
            recursive_beliefs={"沈砚": {"沈砚": {"沈砚已死": _b("沈砚已死", "已死", 0.8)}}}
        ),
        "沈砚": _s(world_beliefs={"沈砚已死": _b("沈砚已死", "已死", 0.9)}),
    }
    pts = [p for p in derive_tension_points(agree, {}) if p.type is TensionType.RECURSIVE_MISMATCH]
    t.eq(pts, [], "A 的建模正确 → 不报递归错位")

    # A 对 B 的建模与 B 的实际信念相反 → 报
    wrong = {
        "陈默": _s(
            recursive_beliefs={"沈砚": {"沈砚": {"沈砚已死": _b("沈砚已死", "已死", 0.8)}}}
        ),
        "沈砚": _s(world_beliefs={"沈砚已死": _b("沈砚已死", "活着", 0.9)}),
    }
    pts = [p for p in derive_tension_points(wrong, {}) if p.type is TensionType.RECURSIVE_MISMATCH]
    t.eq(len(pts), 1, "A 的建模与 B 的实际信念相反 → 报")


def test_belief_conflict(t: T) -> None:
    from loom.ir.tom import TensionType, derive_tension_points

    t.group("4b. 信念冲突：两人对同一命题持不同值")

    states = {
        "陈默": _s(world_beliefs={"城墙会塌": _b("城墙会塌", "会", 0.9)}),
        "沈砚": _s(world_beliefs={"城墙会塌": _b("城墙会塌", "不会", 0.5)}),
    }
    pts = [p for p in derive_tension_points(states, {}) if p.type is TensionType.BELIEF_CONFLICT]
    t.eq(len(pts), 1, "同命题不同值 → 1 条冲突")
    t.eq(pts[0].intensity, 0.7, "强度 = (0.9+0.5)/2 = 0.7")
    t.eq(set(pts[0].involved), {"陈默", "沈砚"}, "涉及两人（对称张力，顺序无意义）")

    # 同命题同值 → 不是冲突
    agree = {
        "陈默": _s(world_beliefs={"城墙会塌": _b("城墙会塌", "会", 0.9)}),
        "沈砚": _s(world_beliefs={"城墙会塌": _b("城墙会塌", "会", 0.9)}),
    }
    pts = [p for p in derive_tension_points(agree, {}) if p.type is TensionType.BELIEF_CONFLICT]
    t.eq(pts, [], "同命题同值 → 不报冲突")

    # 只有一方持有该命题 → 不构成「冲突」（只是信息不对称）
    half = {"陈默": _s(world_beliefs={"城墙会塌": _b("城墙会塌", "会", 0.9)}), "沈砚": _s()}
    pts = [p for p in derive_tension_points(half, {}) if p.type is TensionType.BELIEF_CONFLICT]
    t.eq(pts, [], "只有一方持有 → 不报冲突")


def test_secret_exposure(t: T) -> None:
    from loom.ir.tom import TensionType, derive_tension_points

    t.group("4c. 秘密暴露风险：A 以为是秘密，别人已经知情/起疑")

    truth = {"陈默是卧底": "是卧底"}

    # 别人已经知道真相 → 风险
    leaked = {
        "陈默": _s(known_secrets=["陈默是卧底"]),
        "沈砚": _s(world_beliefs={"陈默是卧底": _b("陈默是卧底", "是卧底", 0.9)}),
    }
    pts = [
        p for p in derive_tension_points(leaked, truth)
        if p.type is TensionType.SECRET_EXPOSURE_RISK
    ]
    t.eq(len(pts), 1, "秘密已被他人知悉 → 1 条暴露风险")
    t.eq(pts[0].involved, ["陈默", "沈砚"], "涉及持有人与知情者")
    t.eq(pts[0].intensity, 0.7, "秘密暴露风险强度 0.7")
    t.ok(pts[0].suggestion.strip(), "必须带建议")

    # 只有「起疑」（ToM 第 1 层：A 对 B 的了解里出现了这条）→ 也算风险
    suspect = {
        "陈默": _s(known_secrets=["陈默是卧底"]),
        "沈砚": _s(
            about_others={
                "陈默": {"陈默是卧底": _b("陈默是卧底", "可能是", 0.4, _src("INFERENCE"))}
            }
        ),
    }
    pts = [
        p for p in derive_tension_points(suspect, truth)
        if p.type is TensionType.SECRET_EXPOSURE_RISK
    ]
    t.eq(len(pts), 1, "他人只是起疑（about_others）→ 仍算风险")
    t.eq(pts[0].involved, ["陈默", "沈砚"], "起疑者进入 involved")

    # 同一个人两条路都命中 → 去重，仍只有一条
    both = {
        "陈默": _s(known_secrets=["陈默是卧底"]),
        "沈砚": _s(
            world_beliefs={"陈默是卧底": _b("陈默是卧底", "是卧底", 0.9)},
            about_others={"陈默": {"陈默是卧底": _b("陈默是卧底", "是", 0.4)}},
        ),
    }
    pts = [
        p for p in derive_tension_points(both, truth)
        if p.type is TensionType.SECRET_EXPOSURE_RISK
    ]
    t.eq(len(pts), 1, "同一对（持有人, 知情者）只报一条")

    # 无人知情也无人起疑 → 秘密是安全的
    safe = {"陈默": _s(known_secrets=["陈默是卧底"]), "沈砚": _s()}
    pts = [
        p for p in derive_tension_points(safe, truth)
        if p.type is TensionType.SECRET_EXPOSURE_RISK
    ]
    t.eq(pts, [], "无人知情 → 不报风险")


def test_goal_conflict(t: T) -> None:
    from loom.ir.tom import TensionType, derive_tension_points

    t.group("4d. 目标冲突：两个角色追同一个目标")

    states = {
        "陈默": _s(active_goals=["夺回钥匙", "活下去"]),
        "沈砚": _s(active_goals=["夺回钥匙"]),
    }
    pts = [p for p in derive_tension_points(states, {}) if p.type is TensionType.GOAL_CONFLICT]
    t.eq(len(pts), 1, "共享一个目标 → 1 条")
    t.eq(set(pts[0].involved), {"陈默", "沈砚"}, "涉及两人（对称张力，顺序无意义）")
    t.eq(pts[0].intensity, 0.6, "目标冲突强度 0.6")

    solo = {"陈默": _s(active_goals=["夺回钥匙"]), "沈砚": _s(active_goals=["活下去"])}
    pts = [p for p in derive_tension_points(solo, {}) if p.type is TensionType.GOAL_CONFLICT]
    t.eq(pts, [], "目标不同 → 不报")


# ---------------------------------------------------------------------------
# 5. 【核心】张力点是生成资产：每个都必须带走一条建议
# ---------------------------------------------------------------------------


def test_every_point_carries_suggestion(t: T) -> None:
    from loom.ir.tom import TensionPoint, TensionType, derive_tension_points

    t.group("5. 【核心】每个张力点都必须带走「接下来写什么」")

    states, truth = _scenario()
    pts = derive_tension_points(states, truth)

    t.ok(bool(pts), "场景确实产出了张力点")
    t.ok(
        all(p.suggestion and p.suggestion.strip() for p in pts),
        "所有张力点的 suggestion 非空",
    )
    t.ok(
        all(p.description and p.description.strip() for p in pts),
        "所有张力点的 description 非空",
    )
    # 建议必须与描述不同 —— 复读一遍描述等于没给建议
    t.ok(
        all(p.suggestion != p.description for p in pts),
        "suggestion 不是 description 的复读",
    )

    # schema 层面就不允许「只报问题、不给下一步」
    t.ok(
        raises(
            lambda: TensionPoint(
                type=TensionType.DRAMATIC_IRONY,
                involved=["陈默"],
                intensity=0.8,
                description="读者知道真相，陈默不知道",
            )
        ),
        "缺 suggestion → 构造失败",
    )
    t.ok(
        raises(
            lambda: TensionPoint(
                type=TensionType.DRAMATIC_IRONY,
                involved=["陈默"],
                intensity=0.8,
                description="d",
                suggestion="",
            )
        ),
        "空 suggestion → 构造失败",
    )
    t.ok(
        raises(
            lambda: TensionPoint(
                type=TensionType.DRAMATIC_IRONY,
                involved=[],
                intensity=0.8,
                description="d",
                suggestion="s",
            )
        ),
        "空 involved → 构造失败",
    )
    t.ok(
        raises(
            lambda: TensionPoint(
                type=TensionType.DRAMATIC_IRONY,
                involved=["陈默"],
                intensity=1.5,
                description="d",
                suggestion="s",
            )
        ),
        "intensity 越界 → 构造失败",
    )


def test_determinism_and_edges(t: T) -> None:
    from loom.ir.tom import derive_tension_points

    t.group("6. 确定性与边界")

    t.eq(derive_tension_points({}, {}), [], "空输入 → 空输出")
    t.eq(
        derive_tension_points({"陈默": _s()}, {"沈砚已死": "已死"}),
        [],
        "有角色但无信念 → 空输出",
    )
    t.eq(
        derive_tension_points(*_scenario()),
        derive_tension_points(*_scenario()),
        "同一输入两次调用结果完全相同（确定性）",
    )

    # 秘密不在真值层 → 无从判定暴露，保守不报
    orphan = {
        "陈默": _s(known_secrets=["没登记的命题"]),
        "沈砚": _s(world_beliefs={"没登记的命题": _b("没登记的命题", "真", 0.9)}),
    }
    from loom.ir.tom import TensionType

    pts = [
        p for p in derive_tension_points(orphan, {})
        if p.type is TensionType.SECRET_EXPOSURE_RISK
    ]
    t.eq(pts, [], "秘密不在真值层 → 不报风险")


# ---------------------------------------------------------------------------


def main() -> int:
    print("═" * 64)
    print("  ToM 信念层与张力生成 —— 测试（TDD）")
    print("═" * 64)
    t = T()
    try:
        test_belief_model(t)
        test_dramatic_irony(t)
        test_intensity_ordering(t)
        test_recursive_mismatch(t)
        test_belief_conflict(t)
        test_secret_exposure(t)
        test_goal_conflict(t)
        test_every_point_carries_suggestion(t)
        test_determinism_and_edges(t)
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
