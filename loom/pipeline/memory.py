"""动态叙事记忆（Dynamic Narrative Memory）—— Loom 目前**完全缺失**的那一层。

── 为什么要有这个模块（研究证据）────────────────────────────────────────
ConWriter（EMNLP 2026 Findings，arXiv 2608.05169）用「动态叙事记忆 + 符号
状态转移校验」两件事，把长篇一致性错误密度降了 50–88%。真正决定本模块优先级
的是它的**消融实验**：

    full                        错误密度 0.1335
    − 符号状态转移校验          0.6843   （恶化 413%）
    − 动态叙事记忆              0.7499   （恶化 462%）

**去掉记忆比去掉校验更糟 —— 记忆的贡献大于校验。** 而 Loom 只做了其中一半：
`StateDelta` + 结构校验器就是「符号状态转移校验」那一半；「动态叙事记忆」
这一半此前**不存在** —— 没有对象随场景推进而更新、能被后续场景检索。
本模块补的正是这一半，按消融证据排序，它是 Loom 当前最大的单点能力缺口。

── 与 lore 的边界（**不合并**）──────────────────────────────────────────
`Lorebook`（LoreSeeder 产出） = **世界知识**：什么是什么。常驻 / 关键词触发 /
递归激活，**不随场景推进而改变**。
`NarrativeMemory`（本模块）   = **叙事状态**：现在是什么样。随场推进，会被
`StateDelta` 反复改写。

分开的唯一理由是**判据**：合并后「该注入什么」就没有判据了 —— lore 由关键词
命中率决定注入，memory 由「与当前场景的实体 / 聚焦者的相关性 + 确立时间」决定
注入。混进同一个桶就只能共用一套策略，两边一起退化：lore 会被最新状态覆盖
（百科变成流水账），memory 会被常驻条目灌满（检索失去时序信号）。
所以界线是硬的：**会被 state_deltas 改写的，一律进 memory；不会的，一律进 lore。**

概念上这条界线就是 Herman（2002, *Story Logic*）的 storyworld：故事世界是
「被叙事事件反复重构的当前状态」—— 重构它的那部分是可变的（memory），
重构所依据的常识是不变的（lore）。

── 确定性 ──────────────────────────────────────────────────────────────
同样的场景序列必须得到逐字节相同的 `to_json()`：不取时钟、不取随机、不依赖
dict 遍历顺序（所有检索结果显式排序）。时间一律来自 `SceneNode` 的
`fabula_time.day` / `sjuzhet_index` —— 由调用方（IR）提供，本模块不发明时间。

── 为什么必须能持久化 ──────────────────────────────────────────────────
铁律是「IR 才是真值」。一份只能在内存里活的记忆会变成**第二份真值**：它和 IR
必然漂移，且漂移不可见、不可审计、不可 diff。所以本模块是 pydantic 模型 +
`to_json` / `from_json`，能被 checkpoint 一起落盘、能被比对、能被回放。
代价（也是设计约束）：`value` / `before` 必须是 **JSON 往返守恒**的普通数据，
构造时即校验；不能塞对象、set、tuple。

── 故意不做的事 ────────────────────────────────────────────────────────
不提供 `replay(ir)` 从 IR 重建记忆。IR 的 `state_deltas` 只承载 `state` 类记录，
`knowledge` 与 `commitment` 类记录不落在 IR 里；做一个只能重建 1/3 的 replay
是「看似可重建、实则缺一半」的假能力，比不做更危险。
"""

from __future__ import annotations

import json
from typing import Any, Literal, Sequence

from pydantic import Field, model_validator

from ..ir.base import LoomModel
from ..ir.models import SceneNode

MEMORY_SCHEMA_VERSION = "1.0.0"

MemoryKind = Literal["state", "knowledge", "commitment"]
"""三类记忆，与 ConWriter 的符号状态转移一一对应：

    state       —— 实体当前处于什么状态（`StateDelta` 的落点）
    knowledge   —— 角色知道什么 / 不知道什么（知情矩阵的可变部分）
    commitment  —— 承诺已兑现到什么程度（0..1 的进度，不是布尔）

分开存而不是合并成一个 `dict[str, Any]`：`commitment` 的进度语义是数值，
`knowledge` 的语义是布尔，混在一起就无法对它们各自做校验与查询。
"""

_DEFAULT_KINDS: tuple[MemoryKind, ...] = ("state", "knowledge", "commitment")


def memory_key(kind: MemoryKind, subject: str, attribute: str) -> str:
    """记忆键。格式 `kind:subject:attribute`，三类记忆共享一个命名空间。"""
    return f"{kind}:{subject}:{attribute}"


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class MemoryRecord(LoomModel):
    """一条记忆。

    `established_at_scene` / `established_at_day` / `sjuzhet_index` 三件套是
    **溯源字段**：回答「这个事实是在第几场确立的」。没有它们，第 30 场召回
    第 3 场埋的事实时就无法说明它从哪来，也无法判断它是否已经过期 ——
    而这恰恰是长篇「吃书」最常见的形态。
    """

    id: str
    key: str
    kind: MemoryKind
    subject: str
    attribute: str
    value: Any
    before: Any = None

    established_at_scene: str
    established_at_day: int = Field(default=0, ge=0)
    sjuzhet_index: int = Field(default=0, ge=0)

    supersedes: str | None = Field(
        default=None, description="被本条覆盖的那条记录的 id（覆盖链，用于溯源）"
    )
    note: str = ""

    @model_validator(mode="after")
    def _must_persist(self) -> MemoryRecord:
        """持久化守恒检查：值必须 JSON 往返不变。

        这不是洁癖。允许不可序列化的值，等价于允许一份「能读出来但存不回去」
        的记忆 —— `to_json → from_json` 不守恒，铁律就破了。宁可在构造时
        炸掉，也不要在落盘后才发现对不上。
        """
        for name in ("value", "before"):
            v = getattr(self, name)
            if v is None:
                continue
            try:
                round_tripped = json.loads(json.dumps(v, ensure_ascii=False))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"MemoryRecord.{name} 不可 JSON 序列化（{v!r}）："
                    f"记忆必须可持久化 —— {exc}"
                ) from exc
            if round_tripped != v:
                raise ValueError(
                    f"MemoryRecord.{name} 的 JSON 往返不守恒（{v!r} → {round_tripped!r}）："
                    "会让 to_json → from_json 不相等。请用普通 JSON 数据"
                    "（str / int / float / bool / None / list / dict[str, ...]）。"
                )
        return self


class NarrativeMemory(LoomModel):
    """随场景推进而更新的叙事状态。

    两份存储的取舍：

        records  —— 当前视图（每键一条），`state_of` 是 O(1) 查表
        history  —— 追加日志（每条写入留痕），被覆盖的旧值只在这里还活着

    只留 records 就丢了「谁在第几场把它改成这样的」（溯源不成立）；
    只留 history 则每次查询都要扫全表，`state_of` 退化成 O(n)。
    两者都是同一批 `MemoryRecord`，不存在不同步 —— records 里的每条都能在
    history 里找到同一 `id`。
    """

    schema_version: str = MEMORY_SCHEMA_VERSION
    records: dict[str, MemoryRecord] = Field(default_factory=dict)
    history: list[MemoryRecord] = Field(default_factory=list)
    seq: int = Field(
        default=0,
        ge=0,
        description="单调序号。持久化时一并落盘，否则回读后新 id 会与旧 id 撞车。",
    )

    # --- 写入 ---

    def commit(self, scene: SceneNode) -> list[MemoryRecord]:
        """提交一场的 `state_deltas` 到记忆。

        只处理 `state_deltas`：**那是 IR 里唯一的可信状态变化通道**。
        不从 `turning_point` / `prose` 里猜状态 —— 猜出来的东西既溯源不到
        方法论，也无法与校验器对齐（这正是本项目禁止的「看起来合理的启发式」）。

        返回本场写入的记录（按 delta 顺序），便于调用方审计。
        """
        out: list[MemoryRecord] = []
        for d in scene.state_deltas:
            out.append(
                self._write(
                    kind="state",
                    subject=d.entity_id,
                    attribute=d.attribute,
                    value=d.after,
                    before=d.before,
                    scene_id=scene.id,
                    day=scene.fabula_time.day,
                    sjuzhet_index=scene.sjuzhet_index,
                    note=f"{scene.title}：{d.entity_id}.{d.attribute} "
                    f"{_as_text(d.before)} → {_as_text(d.after)}",
                )
            )
        return out

    def observe(
        self,
        scene: SceneNode,
        character_id: str,
        fact: str,
        *,
        knows: bool = True,
        note: str = "",
    ) -> MemoryRecord:
        """记录「谁在第几场知道了什么」。

        `knows=False` 是**显式的不知情**，不是「没记录」：戏剧反讽需要一个
        可比对的三值（知道 / 不知道 / 没建模），少一个就无法校验视角越界。
        """
        return self._write(
            kind="knowledge",
            subject=character_id,
            attribute=fact,
            value=knows,
            scene_id=scene.id,
            day=scene.fabula_time.day,
            sjuzhet_index=scene.sjuzhet_index,
            note=note or f"{character_id} {'得知' if knows else '未知'}：{fact}",
        )

    def advance_commitment(
        self,
        scene: SceneNode,
        commitment_id: str,
        progress: float,
        *,
        note: str = "",
    ) -> MemoryRecord:
        """记录承诺已兑现到什么程度（`0..1` 进度，不是布尔）。

        用进度而非布尔：承诺是**逐步兑现**的，「兑现了多少」正是判断
        「这一场该不该再推一把」的输入；布尔只能回答是否已结束。
        """
        if not 0.0 <= progress <= 1.0:
            raise ValueError(f"progress 必须落在 [0, 1]，实际 {progress!r}")
        return self._write(
            kind="commitment",
            subject=commitment_id,
            attribute="progress",
            value=float(progress),
            scene_id=scene.id,
            day=scene.fabula_time.day,
            sjuzhet_index=scene.sjuzhet_index,
            note=note or f"{commitment_id} 兑现进度 {progress:.2f}",
        )

    def _write(
        self,
        *,
        kind: MemoryKind,
        subject: str,
        attribute: str,
        value: Any,
        scene_id: str,
        day: int,
        sjuzhet_index: int,
        before: Any = None,
        note: str = "",
    ) -> MemoryRecord:
        key = memory_key(kind, subject, attribute)
        self.seq += 1
        prev = self.records.get(key)
        rec = MemoryRecord(
            id=f"{key}#{self.seq}",
            key=key,
            kind=kind,
            subject=subject,
            attribute=attribute,
            value=value,
            before=before,
            established_at_scene=scene_id,
            established_at_day=day,
            sjuzhet_index=sjuzhet_index,
            supersedes=prev.id if prev is not None else None,
            note=note,
        )
        self.records[key] = rec
        self.history.append(rec)
        return rec

    # --- 读取 ---

    def state_of(self, entity_id: str) -> dict[str, Any]:
        """某实体**当前**的状态（后写覆盖先写的结果）。"""
        return {
            r.attribute: r.value
            for r in self.records.values()
            if r.kind == "state" and r.subject == entity_id
        }

    def knowledge_of(self, character_id: str) -> dict[str, bool]:
        """某角色**当前**的知情情况。缺省 = 该事实没被建模（不是 False）。"""
        return {
            r.attribute: bool(r.value)
            for r in self.records.values()
            if r.kind == "knowledge" and r.subject == character_id
        }

    def progress_of(self, commitment_id: str) -> float:
        """某承诺**当前**的兑现进度。未记录则 0.0。"""
        for r in self.records.values():
            if r.kind == "commitment" and r.subject == commitment_id:
                return float(r.value)
        return 0.0

    def established_in(self, key: str) -> str | None:
        """这个事实是在第几场确立的。key 用 `memory_key(...)` 构造。

        返回场景 id；从未确立过返回 `None`。这是「长程召回」的另一半：
        召回到事实还不够，还要知道它从哪来、是否已被后来的场次覆盖。
        """
        rec = self.records.get(key)
        return rec.established_at_scene if rec is not None else None

    def recall(
        self,
        query: str = "",
        *,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 20,
        include_superseded: bool = False,
    ) -> list[MemoryRecord]:
        """检索与 `query` 相关的记忆。

        匹配是**字面子串**（subject / attribute / note / value / before，
        大小写不敏感），不是向量召回 —— 与 lore 同理：长篇里「该出现时没出现」
        是致命的，概率性召回不可接受。

        排序：**最近确立的优先**（`sjuzhet_index` 降序，key 与 id 兜底）。
        当前场景要注入的是「世界现在是什么样」，越新的记录越有权威性。

        `include_superseded=True` 时连已被覆盖的旧值一起召回（走 `history`），
        供溯源与「他曾经是什么样」的追问。
        """
        wanted = tuple(kinds) if kinds is not None else _DEFAULT_KINDS
        pool = self.history if include_superseded else list(self.records.values())
        q = query.strip().lower()
        hits = [
            r
            for r in pool
            if r.kind in wanted
            and (
                not q
                or q
                in "\n".join(
                    [
                        r.subject,
                        r.attribute,
                        r.note,
                        _as_text(r.value),
                        _as_text(r.before),
                    ]
                ).lower()
            )
        ]
        hits.sort(key=lambda r: (-r.sjuzhet_index, r.key, r.id))
        return hits[:limit]

    def relevant_to(
        self,
        scene: SceneNode,
        *,
        limit: int = 20,
        include_superseded: bool = False,
    ) -> list[MemoryRecord]:
        """与当前场景相关的记忆 —— 供 Scripter 注入。

        相关性判据就是场景卡上写了什么：`entities` ∪ `{focalizer, narrator}`。
        不引入别的信号（不猜主题、不算相似度）：场景卡是 IR 的既有真值，
        除此之外的一切相关性打分都是无源启发式。

        排序：**按叙事顺序升序**（与 `recall` 相反）。注入给 Scripter 的
        简报要按故事推进顺序读，读者/模型的时序感才不会被打乱。
        """
        ids = set(scene.entities) | {scene.focalizer, scene.narrator}
        pool = self.history if include_superseded else list(self.records.values())
        hits = [r for r in pool if r.subject in ids]
        hits.sort(key=lambda r: (r.sjuzhet_index, r.key, r.id))
        return hits[:limit]

    def brief_for(self, scene: SceneNode, *, limit: int = 20) -> str:
        """渲染成可注入的文本简报。文本只是本结构的一个视图。"""
        recs = self.relevant_to(scene, limit=limit)
        if not recs:
            return "（无相关记忆）"
        return "\n".join(
            f"- [{r.kind}] {r.subject}.{r.attribute} = {_as_text(r.value)}"
            f"（第 {r.established_at_scene} 场 / 第 {r.established_at_day} 天确立）"
            for r in recs
        )

    # --- 持久化 ---

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, raw: str) -> NarrativeMemory:
        return cls.model_validate_json(raw)


__all__ = [
    "MEMORY_SCHEMA_VERSION",
    "MemoryKind",
    "MemoryRecord",
    "NarrativeMemory",
    "memory_key",
]
