"""动态叙事记忆（`loom/pipeline/memory.py`）的单元测试。

跑法：
    .venv/Scripts/python.exe tests/test_memory.py

零依赖（不用 pytest），与 `tests/test_checkpoint.py` / `test_telemetry.py` 同风格。
IR 全部在**本文件**里构造（不动 `tests/fixtures.py`）：共享 fixture 是集成方
串行编辑的文件，往里塞东西会与别人的改动互踩。

── 这个模块最容易「假绿」的三处，也是本文件的重心 ──────────────────────

  1. **召回是空的但测试全绿。** 一个永远返回「我记得一切」的记忆，和一个
     真的能跨 15 场召回的记忆，在只断言「返回非空」时长得一模一样。所以
     长程用例必须是**具体事实**：第 3 场埋 `沈砚.status = 死亡`，第 18 场
     断言取回的**值**就是「死亡」；并且配一条**反例** —— 空记忆在第 18 场
     召回同一查询必须为空。没有反例，正例等于没判。
  2. **覆盖被当成新增。** 「后写覆盖先写」如果实现成了追加，`state_of` 会
     返回最后一条，测试仍然绿 —— 看起来对，实则 `records` 里攒了一堆垃圾，
     `established_in` 也会返回旧场。所以覆盖用例必须同时断言
     `state_of` == 新值 **且** 只有一个当前记录 **且** 旧值只在 `history`
     里活着（要靠 `include_superseded` 才能召回）。
  3. **持久化往返是「能跑」不是「守恒」。** `to_json → from_json` 只要不抛异常
     就算通过，但值域被悄悄换掉（set 变 list、tuple 变 list）照样不报错。
     所以本模块在**构造时**就拒绝 JSON 往返不守恒的值，这里专门测两条：
     set（不可序列化）与 tuple（可序列化但不守恒）都必须被拒。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.ir.models import (  # noqa: E402
    LoreEntry,
    Lorebook,
    SceneNode,
    StateDelta,
    TimePoint,
)
from loom.pipeline import memory as mem  # noqa: E402
from loom.pipeline.memory import (  # noqa: E402
    MemoryRecord,
    NarrativeMemory,
    memory_key,
)


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> None:
        if cond:
            self.passed += 1
        else:
            self.failed.append(label if not detail else f"{label}\n      {detail}")

    def eq(self, got, want, label: str) -> None:
        self.ok(
            got == want,
            label,
            f"期望 {want!r}，实际 {got!r}",
        )

    def group(self, name: str) -> None:
        print(f"\n  {name}")


# ---------------------------------------------------------------------------
# 素材：20 场序列
# ---------------------------------------------------------------------------

_DEAD = "死亡"


def _scene(
    i: int,
    *,
    deltas: tuple[StateDelta, ...] = (),
    entities: tuple[str, ...] = (),
    focalizer: str = "c1",
) -> SceneNode:
    return SceneNode(
        id=f"s{i}",
        title=f"第 {i} 场",
        focalizer=focalizer,
        narrator="narrator",
        fabula_time=TimePoint(day=i),
        sjuzhet_index=i,
        value="信任",
        value_charge_start="-",
        value_charge_end="+",
        goal=f"他要在第 {i} 场确认一件事",
        conflict="纸面在抗拒",
        turning_point=f"第 {i} 次转折",
        outcome="yes_but",
        entities=list(entities),
        state_deltas=list(deltas),
    )


def _d(entity: str, attribute: str, before: str, after: str) -> StateDelta:
    return StateDelta(
        entity_id=entity, attribute=attribute, before=before, after=after
    )


def _twenty() -> tuple[list[SceneNode], NarrativeMemory]:
    """20 场序列：第 3 场埋「沈砚死亡 + 青釭剑易主」，第 11 场二次易主。

    其余 17 场是**干扰项**：它们各自写一条与查询无关的记忆。没有干扰项，
    「返回全部」的实现也能通过召回测试 —— 这是第 1 条假绿的防线。
    """
    scenes: list[SceneNode] = []
    for i in range(1, 21):
        deltas: tuple[StateDelta, ...] = ()
        entities: tuple[str, ...] = ()
        if i == 3:
            deltas = (
                _d("沈砚", "status", "alive", _DEAD),
                _d("青釭剑", "owner", "沈砚", "崔九"),
            )
        elif i == 11:
            deltas = (_d("青釭剑", "owner", "崔九", "阿沁"),)
        else:
            deltas = (_d(f"路人{i}", "心情", "平静", "波动"),)
        if i == 18:
            entities = ("沈砚", "青釭剑")
        scenes.append(_scene(i, deltas=deltas, entities=entities))

    m = NarrativeMemory()
    for s in scenes:
        m.commit(s)
    return scenes, m


# ---------------------------------------------------------------------------
# 1. 提交
# ---------------------------------------------------------------------------


def test_commit(t: T) -> None:
    t.group("提交：state_deltas 落进记忆")

    s3 = _scene(
        3,
        deltas=(_d("沈砚", "status", "alive", _DEAD),),
        entities=("沈砚",),
    )
    m = NarrativeMemory()
    written = m.commit(s3)

    t.eq(len(written), 1, "一场一个 delta → 写入一条")
    t.eq(m.state_of("沈砚"), {"status": _DEAD}, "state_of 取到 after 值")
    t.eq(
        m.established_in(memory_key("state", "沈砚", "status")),
        "s3",
        "溯源：事实确立于第 3 场",
    )
    t.eq(written[0].before, "alive", "保留 before（可逆推）")
    t.eq(written[0].established_at_day, 3, "fabula day 来自 IR，不是时钟")

    t.eq(m.commit(_scene(4)), [], "无 delta 的场景写入 0 条（不是空转）")
    t.eq(len(m.history), 1, "history 只记真实写入")


# ---------------------------------------------------------------------------
# 2. 覆盖
# ---------------------------------------------------------------------------


def test_supersede(t: T) -> None:
    t.group("覆盖：后写覆盖先写，旧值退到 history")

    m = NarrativeMemory()
    m.commit(_scene(5, deltas=(_d("青釭剑", "owner", "沈砚", "崔九"),)))
    m.commit(_scene(9, deltas=(_d("青釭剑", "owner", "崔九", "阿沁"),)))

    t.eq(m.state_of("青釭剑"), {"owner": "阿沁"}, "当前值 = 最后一次写入")
    t.eq(
        m.established_in(memory_key("state", "青釭剑", "owner")),
        "s9",
        "确立场跟着更新到第 9 场（不是第 5 场）",
    )
    t.eq(len(m.records), 1, "当前视图只有一条 —— 覆盖不是追加")
    t.eq(len(m.history), 2, "history 保留两条（可溯源）")
    t.eq(m.records[memory_key("state", "青釭剑", "owner")].supersedes,
         m.history[0].id, "覆盖链指向被覆盖的那条")

    cur = m.recall("青釭剑")
    t.eq([r.value for r in cur], ["阿沁"], "默认只召回当前值")
    allv = m.recall("青釭剑", include_superseded=True)
    t.eq([r.value for r in allv], ["阿沁", "崔九"], "含被覆盖值时按新→旧返回")


# ---------------------------------------------------------------------------
# 3. 长程召回（含反例）
# ---------------------------------------------------------------------------


def test_long_range_recall(t: T) -> None:
    t.group("长程召回：第 3 场埋的事实，第 18 场仍能召回")

    scenes, m = _twenty()
    s18 = scenes[17]

    t.eq(len(m.records), 20, "20 场共留下 20 条当前记录（干扰项在场）")

    hits = m.recall("沈砚")
    t.eq(len(hits), 1, "召回是精确的：干扰项没有被带出来")
    t.eq(hits[0].value, _DEAD, "第 18 场召回第 3 场的事实，值仍然正确")
    t.eq(hits[0].established_at_scene, "s3", "并且知道它来自第 3 场")
    t.eq(m.state_of("沈砚")["status"], _DEAD, "state_of 长程一致")

    rel = m.relevant_to(s18)
    subjects = {r.subject for r in rel}
    t.ok("沈砚" in subjects, "第 18 场的场景卡能带出沈砚", f"实际 {sorted(subjects)}")
    t.ok("青釭剑" in subjects, "第 18 场的场景卡能带出青釭剑", f"实际 {sorted(subjects)}")
    t.eq([r.established_at_scene for r in rel], ["s3", "s11"],
         "简报按叙事顺序升序（s3 先于 s11）")
    t.ok("第 s3 场" in m.brief_for(s18), "简报文本带溯源场次")

    t.eq(m.recall("", limit=50), m.recall("", limit=50), "召回是纯函数（可重复）")
    t.eq(len(m.recall("", limit=5)), 5, "limit 生效")

    # --- 反例：没有记忆就召不回来。没有这一条，上面的用例等于没判 ---
    empty = NarrativeMemory()
    t.eq(empty.recall("沈砚"), [], "空记忆召回为空（反例成立）")
    t.eq(empty.state_of("沈砚"), {}, "空记忆的 state_of 为空（反例成立）")
    t.eq(empty.relevant_to(s18), [], "空记忆对第 18 场无相关记忆")
    t.eq(empty.brief_for(s18), "（无相关记忆）", "空记忆的简报是显式占位")


# ---------------------------------------------------------------------------
# 4. 知情与承诺进度
# ---------------------------------------------------------------------------


def test_knowledge_and_commitment(t: T) -> None:
    t.group("知情 / 承诺：另两类记忆各归各位")

    m = NarrativeMemory()
    s6 = _scene(6)
    s7 = _scene(7)
    m.observe(s6, "崔九", "沈砚已死")
    m.observe(s6, "阿沁", "沈砚已死", knows=False)

    t.eq(m.knowledge_of("崔九"), {"沈砚已死": True}, "知道")
    t.eq(m.knowledge_of("阿沁"), {"沈砚已死": False}, "**显式**不知道（不是缺记录）")
    t.eq(m.knowledge_of("未出场者"), {}, "未建模 ≠ False")

    m.advance_commitment(s6, "cm_揭示真相", 0.3)
    m.advance_commitment(s7, "cm_揭示真相", 0.8)
    t.eq(m.progress_of("cm_揭示真相"), 0.8, "承诺进度后写覆盖先写")
    t.eq(m.progress_of("未登记的承诺"), 0.0, "未登记的承诺进度为 0")

    t.eq(
        m.established_in(memory_key("commitment", "cm_揭示真相", "progress")),
        "s7",
        "承诺进度也能溯源到第几场",
    )

    # 三类记忆共用一个命名空间但互不干扰
    # 注意是 3 不是 4：两条 commitment 同键，后写覆盖先写，只占一个键
    t.eq(len(m.records), 3, "2 条知情 + 1 条承诺（同键覆盖后），互不干扰")
    t.eq([r.kind for r in m.recall("沈砚已死")], ["knowledge", "knowledge"],
         "按 kind 可分别检索")
    t.eq(m.recall("沈砚", kinds=("state",)), [], "kinds 过滤生效（state 里没有沈砚）")

    bad = False
    try:
        m.advance_commitment(s7, "cm_x", 1.5)
    except ValueError:
        bad = True
    t.ok(bad, "进度越界被拒（0..1 是硬约束）")


# ---------------------------------------------------------------------------
# 5. 持久化往返 + 确定性
# ---------------------------------------------------------------------------


def test_persistence(t: T) -> None:
    t.group("持久化：to_json → from_json 守恒，且可确定性复现")

    scenes, m = _twenty()
    m.observe(scenes[17], "c1", "沈砚已死")
    m.advance_commitment(scenes[17], "cm_揭示真相", 0.5)

    raw = m.to_json()
    back = NarrativeMemory.from_json(raw)

    t.eq(back.to_json(), raw, "往返逐字节守恒（不是「能跑」就行）")
    t.eq(back.state_of("沈砚"), m.state_of("沈砚"), "状态往返一致")
    t.eq(back.knowledge_of("c1"), m.knowledge_of("c1"), "知情往返一致")
    t.eq(back.progress_of("cm_揭示真相"), m.progress_of("cm_揭示真相"), "进度往返一致")
    t.eq(back.established_in(memory_key("state", "沈砚", "status")), "s3",
         "溯源往返一致")
    t.eq(len(back.history), len(m.history), "history 往返一致")

    # 回读后继续写入：seq 一并持久化，id 不会与旧记录撞车
    before_ids = {r.id for r in back.history}
    new = back.commit(_scene(21, deltas=(_d("沈砚", "status", _DEAD, "传说"),)))
    t.ok(new[0].id not in before_ids, "回读后新写入的 id 不与旧 id 冲突")

    # 确定性：同样的输入序列，两次独立构建必须逐字节相同
    _, m2 = _twenty()
    m2.observe(scenes[17], "c1", "沈砚已死")
    m2.advance_commitment(scenes[17], "cm_揭示真相", 0.5)
    t.eq(m2.to_json(), raw, "同样序列 → 同样记忆（无时钟、无随机、无遍历序依赖）")

    # 顺序敏感：换序是另一段叙事，不该得到同一份记忆
    m3 = NarrativeMemory()
    for s in reversed(scenes):
        m3.commit(s)
    t.ok(m3.to_json() != raw, "换序是另一段叙事（记忆不是无序集合）")


# ---------------------------------------------------------------------------
# 6. 与 lore 的边界
# ---------------------------------------------------------------------------


def test_lore_boundary(t: T) -> None:
    t.group("与 lore 的边界：世界知识常驻，叙事状态随场推进")

    lore = Lorebook()
    lore.add(
        LoreEntry(
            id="lore_青釭剑",
            keys=["青釭剑"],
            content="青釭剑：一柄铸于前朝的古剑",
            is_constant=True,
        )
    )
    lore.add(
        LoreEntry(
            id="lore_崔九",
            keys=["崔九"],
            content="崔九：渡口守夜人",
        )
    )

    m = NarrativeMemory()
    m.commit(_scene(3, deltas=(_d("青釭剑", "owner", "沈砚", "崔九"),)))
    m.commit(_scene(11, deltas=(_d("青釭剑", "owner", "崔九", "阿沁"),)))

    text = "第 18 场：阿沁摩挲着青釭剑的剑脊。"
    compiled = lore.compile(text)
    t.eq(len(compiled), 1, "lore 按关键词命中（与记忆无关）")
    t.ok("阿沁" not in compiled[0].content,
         "lore 不记录叙事状态 —— 易主两次后百科条目原样未动")
    t.eq(m.state_of("青釭剑")["owner"], "阿沁", "易主这件事只活在 memory 里")

    # 反过来：世界知识不进 memory
    t.eq(m.recall("铸于前朝"), [], "memory 不存世界知识（那是 lore 的活）")
    t.eq(m.state_of("青釭剑").get("material"), None,
         "记忆里没有未被 state_deltas 改写过的属性")

    # 判据：lore 是关键词/常驻驱动，memory 是场景卡相关性驱动 —— 两套策略，不合并
    t.eq({e.id for e in lore.compile("阿沁摩挲着青釭剑。")}, {"lore_青釭剑"},
         "非常驻条目：关键词命中才注入")
    t.eq({e.id for e in lore.compile("阿沁今天什么都没做。")}, {"lore_青釭剑"},
         "常驻条目：无条件注入 —— memory 里没有「常驻」这种东西")
    s_no_entity = _scene(19, entities=("路人19",), focalizer="c1")
    t.ok(all(r.subject != "青釭剑" for r in m.relevant_to(s_no_entity)),
         "memory 未提实体则不注入（场景卡驱动，无强制命中）")


# ---------------------------------------------------------------------------
# 7. 持久化守恒的硬约束
# ---------------------------------------------------------------------------


def test_value_must_persist(t: T) -> None:
    t.group("值域约束：JSON 往返不守恒的值一律拒绝")

    base = dict(
        id="r1",
        key=memory_key("state", "e", "a"),
        kind="state",
        subject="e",
        attribute="a",
        established_at_scene="s1",
    )
    rejected = 0
    for bad in ({"a", "b"}, ("a", "b"), object()):
        try:
            MemoryRecord(**base, value=bad)
        except ValueError:
            rejected += 1
    t.eq(rejected, 3, "set / tuple / 对象 全被拒（不是静默降级）")

    m = NarrativeMemory()
    for ok_value in ("文本", 3, 0.5, True, None, [1, 2], {"k": "v"}):
        m._write(
            kind="state",
            subject="e",
            attribute=f"a{_as_key(ok_value)}",
            value=ok_value,
            scene_id="s1",
            day=1,
            sjuzhet_index=1,
        )
    t.eq(NarrativeMemory.from_json(m.to_json()).to_json(), m.to_json(),
         "普通 JSON 数据往返守恒")


def _as_key(v: object) -> str:
    return type(v).__name__


def main() -> int:
    print("═" * 64)
    print("  动态叙事记忆 NarrativeMemory —— 测试")
    print("═" * 64)
    t = T()
    try:
        test_commit(t)
        test_supersede(t)
        test_long_range_recall(t)
        test_knowledge_and_commitment(t)
        test_persistence(t)
        test_lore_boundary(t)
        test_value_must_persist(t)
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
