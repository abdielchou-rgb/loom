"""提案协议 —— 永不静默改写。

    方法论出处
    ────────────────────────────────────────────────────────────
    Horvitz, E. (1999). "Principles of Mixed-Initiative User Interfaces".
    *Proceedings of CHI '99*, ACM: 159-166.
        —— 混合主动界面的核心原则：系统可以主动提议，但**控制权必须
           留在用户手里**，且系统要能为其提议给出理由（rationale）。
           本文的「直接性 (directability)」与「预期性 (anticipation)」
           两条原则，正是本模块 `Diff.rationale` 与 `ProposalSet` 的
           设计依据：AI 可以生成提案，但作者保留裁决权。

    Amershi, S. et al. (2019). "Guidelines for Human-AI Interaction".
    *Proceedings of CHI '19*, ACM, Paper 3.
        —— 第 6 条「Support efficient dismissal」：用户拒绝 AI 建议
           必须是廉价、一次性的操作。因此本模块的 `reject` 与 `accept`
           完全对称，没有任何「拒绝需要理由」的不对称负担。

    数据结构的直接来源：Æsirian `core/diff_engine.py`（763 行）的
    `Diff` 与 `DiffStatus`，原型是 Pensive 的
    "**what you pin, the AI must keep**"（见 `aesirian_吸收评估.md` ⑦）。

    为什么 Keel 需要它
    ────────────────────────────────────────────────────────────
    `CriticLoop` 会**自动应用**修订（目前只限文风类），结构类问题
    「留给人决策」—— 但没有任何载体承载那个决策，于是实际上等于没发生。
    本模块把「留给人决策」升级为「生成提案，人一键采纳」：

        CriticLoop   文风类 → 自动修（保持现状）
                     结构类 → 产出 Diff 提案（不自动应用）
                     作者     → accept / reject，全程可审计

    「永不静默改写」不是一个态度，是一条**可以被代码检查的性质**：
    消费方读 `Diff.status` 决定是否应用，`Diff.after` 在 status 变成
    `accepted` 之前永远只是「提案内容」，不是「已生效的值」。

    裁决状态机（这是本模块的全部内容）
    ────────────────────────────────────────────────────────────
        pending --accept--> accepted
        pending --reject--> rejected

    状态机只有**一份实现**（模块级 `resolve()`），但有两个入口：
    `ProposalSet.accept/reject` 与 `NarrativeIR.accept_proposal/reject_proposal`
    （IR 的 `proposals` 字段是裸列表）。理由见 `resolve()` 的 docstring。

    重复裁决的两种情形被刻意区别对待：
      * **同向重复**（accepted 之后再 accept）→ **幂等**。
        作者重复点同一个按钮不该产生冲突，界面重试/网络重发更是常态。
      * **反向重复**（accepted 之后再 reject）→ **conflicted**。
        这是作者自相矛盾的事实，是要被**记录下来**的信号，不是要被
        抛掉的异常 —— 决策遥测（`keel/provenance/telemetry.py`）要数它。
        抛异常会让这个信号消失在调用栈里。

    `conflicted` 是终态：再裁决不再翻转。终态可翻转的话，遥测记录到的
    状态会随查询时刻漂移，指标就不可复现了。

    设计说明：本模块**不定义 `__all__`**（理由见 `models.py` 顶部那条教训）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from .base import KeelModel


class DiffStatus(str, Enum):
    """提案的裁决状态。取值同源项目。"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


class Diff(KeelModel):
    """一条结构改动的提案。

    刻意**不**自动应用到目标卡上。`before` / `after` 是提案内容，
    `status` 才是唯一的「是否生效」开关 —— 把这两件事分开，是
    「永不静默改写」能被机器检查的前提。

    字段：
        id            提案 id
        target_card   被改的卡（framework / chapter / biography / sample）
        field         被改的字段名
        before        原值（便于作者看清代价，也便于回滚）
        after         提案值
        rationale     **为什么**要改。Horvitz 1999：系统必须能解释自己的提议。
        source_card   因为哪张卡变了才产生这条提案（传播方向可追溯）
        status        裁决状态，默认 pending
        proposed_at   机器**何时提出**（墙钟 ISO 8601，调用方注入）
        decided_at    人**何时裁决**（墙钟 ISO 8601，调用方注入）
        decided_by    谁裁决的（"human" / "human:<名字>"）

    ── 三个时间/主体字段为什么必须存在 ──────────────────────────
    合规申诉要的是**主张证据**：「这些判断是人类做的」。一条 `status=rejected`
    只说明「有人按了拒绝」，说不出**谁、什么时候**。没有这两个字段，
    「人做过判断」就是一句主张，不是一份记录 —— 而主张不是证据。

    故此三字段的取值纪律：
      * **不取时钟。** 一律由调用方注入（`keel/pipeline/decide` 的
        `decided_at`，CLI 落盘时补墙钟）。理由与 `DecisionTelemetry`
        相同：取 `now()` 的结构写不出确定性测试。
      * `decided_by` **不默认是 "human"**。默认「是人做的」正是本模块
        要防的自欺 —— 判定权在调用方手里，机器代裁就如实写机器。

    ⚠ 命名陷阱（两个 `decided_at` 不是同一个东西）：
    `DecisionTelemetry.DecisionRecord.decided_at` 是**故事内时点标签**
    （如「第 3 章」），服务于产品指标；这里的 `decided_at` 是**墙钟时刻**，
    服务于举证。同名不同义已在两处 docstring 互相点明。
    """

    id: str = Field(min_length=1)
    target_card: str = Field(min_length=1, description="被修改的卡")
    field: str = Field(min_length=1, description="被修改的字段")
    before: Any = Field(description="原值")
    after: Any = Field(description="提案值。status 变为 accepted 之前不得应用。")
    rationale: str = Field(min_length=1, description="为什么这样改（须可被作者复核）")
    source_card: str = Field(min_length=1, description="触发本提案的上游卡")
    status: DiffStatus = Field(
        default=DiffStatus.PENDING, description="裁决状态。默认待裁决 —— 绝不默认生效。"
    )
    proposed_at: str | None = Field(
        default=None, description="机器提出本提案的墙钟时刻（ISO 8601，调用方注入）"
    )
    decided_at: str | None = Field(
        default=None, description="人类裁决的墙钟时刻（ISO 8601，调用方注入）"
    )
    decided_by: str | None = Field(
        default=None, description="裁决主体（如 human）。**不默认填 human** —— 谁裁的誰填。"
    )


def resolve(
    diffs: list[Diff],
    diff_id: str,
    verdict: DiffStatus,
    *,
    decided_at: str | None = None,
    decided_by: str | None = None,
) -> Diff:
    """在**裸 Diff 列表**上执行裁决状态机。

    为什么是模块级函数而不是 `ProposalSet` 的方法：状态机有**两个入口**
    —— `ProposalSet.accept/reject`（当调用方持有集合）与
    `NarrativeIR.accept_proposal/reject_proposal`（当调用方只有 IR，
    而 IR 的 `proposals` 字段是裸列表）。

    若给两个入口各写一份实现，两份必然漂移 —— 而 `conflicted` 这种
    边角语义漂移了没有任何测试会发现（它只在「先接受再拒绝」时出现，
    日常路径根本走不到）。所以状态机只留一份，两个入口都调它。

    三种情形：
      1. `pending` → 落为 verdict
      2. 终态且与 verdict 同向 → 幂等，不动
      3. 终态且与 verdict 反向 → `conflicted`（记录矛盾，不抛异常）

    裁决一个不存在的 id 是编程错误，不是作者行为 —— 必须炸，
    不能静默返回 None（那会让调用方以为裁决成功了）。

    ── `decided_at` / `decided_by` 的落时刻 ──────────────────────
    **只在状态真的发生变化时盖章**，且是覆盖写。取舍：

      同向重复（幂等路径）→ 不盖章。作者重复点按钮不是新的一次判断，
      盖了会把「第一次判断的时刻」冲掉 —— 那正是举证要看的时刻。

      反向翻转（→ conflicted）→ 盖章覆盖。此时 `status` 变成了另一个值，
      若 `decided_at` 还留着上一次的时刻，这条记录就是自相矛盾的：
      它声称「在 T 时刻的裁决结果是 S」，而 T 时刻的裁决结果其实是另一个。
      **status 与 decided_at 必须描述同一次裁决**，宁可丢掉前一次的时刻。

    两个参数都可以不传（None）：那时时间戳留空，状态照常迁移 ——
    「没有时刻的裁决」仍是一次合法裁决，只是举证力弱一些。
    让时间戳的缺失**阻断**裁决，等于让一个元数据字段绑架了控制流。
    """
    diff = next((d for d in diffs if d.id == diff_id), None)
    if diff is None:
        raise KeyError(f"提案不存在: {diff_id}")

    if diff.status is DiffStatus.PENDING:
        diff.status = verdict
        _stamp(diff, decided_at, decided_by)
        return diff

    # 终态：同向幂等，反向记为 conflicted
    if diff.status is DiffStatus.CONFLICTED:
        return diff  # 终态，不再翻转
    if diff.status is verdict:
        return diff  # 同向重复：幂等
    diff.status = DiffStatus.CONFLICTED
    _stamp(diff, decided_at, decided_by)
    return diff


def _stamp(diff: Diff, decided_at: str | None, decided_by: str | None) -> None:
    """落下裁决时刻与裁决主体（见 `resolve` 里关于覆盖取舍的说明）。"""
    if decided_at is not None:
        diff.decided_at = decided_at
    if decided_by is not None:
        diff.decided_by = decided_by


class ProposalSet(KeelModel):
    """一组提案，以及作者的裁决记录。

    这是「永不静默改写」的载体：`CriticLoop` 把结构类问题交到这里，
    作者逐条裁决，下游（遥测、渲染、回写）只读 `status`。
    """

    diffs: list[Diff] = Field(default_factory=list)

    # -- 查询 --

    def get(self, diff_id: str) -> Diff | None:
        """按 id 取提案；不存在返回 None。"""
        return next((d for d in self.diffs if d.id == diff_id), None)

    def pending(self) -> list[Diff]:
        """尚未裁决的提案。这些是作者界面上该显示的东西。"""
        return [d for d in self.diffs if d.status is DiffStatus.PENDING]

    def accepted(self) -> list[Diff]:
        return [d for d in self.diffs if d.status is DiffStatus.ACCEPTED]

    def rejected(self) -> list[Diff]:
        return [d for d in self.diffs if d.status is DiffStatus.REJECTED]

    def conflicted(self) -> list[Diff]:
        return [d for d in self.diffs if d.status is DiffStatus.CONFLICTED]

    def counts(self) -> dict[str, int]:
        """四态计数。**键恒为四种状态**，空集合也返回全零。

        键齐备不是洁癖：缺键会让前端仪表盘 KeyError，而仪表盘崩溃的结果
        是「这个指标没人看」—— 那正是本模块要消灭的东西。
        """
        return {
            "pending": len(self.pending()),
            "accepted": len(self.accepted()),
            "rejected": len(self.rejected()),
            "conflicted": len(self.conflicted()),
        }

    # -- 变更 --

    def add(self, diff: Diff) -> Diff:
        """登记一条提案。id 重复即抛错 —— 重复 id 会让遥测分组被静默污染。"""
        if self.get(diff.id) is not None:
            raise ValueError(f"提案 id 重复: {diff.id}")
        self.diffs.append(diff)
        return diff

    def accept(
        self,
        diff_id: str,
        *,
        decided_at: str | None = None,
        decided_by: str | None = None,
    ) -> Diff:
        """采纳提案。返回被裁决的 Diff（可直接交给决策遥测记录）。"""
        return self._resolve(
            diff_id, DiffStatus.ACCEPTED, decided_at=decided_at, decided_by=decided_by
        )

    def reject(
        self,
        diff_id: str,
        *,
        decided_at: str | None = None,
        decided_by: str | None = None,
    ) -> Diff:
        """拒绝提案。与 accept 完全对称 —— 拒绝必须是廉价的一次性操作
        （Amershi et al. 2019, guideline 6）。"""
        return self._resolve(
            diff_id, DiffStatus.REJECTED, decided_at=decided_at, decided_by=decided_by
        )

    # -- 内部 --

    def _resolve(
        self,
        diff_id: str,
        verdict: DiffStatus,
        *,
        decided_at: str | None = None,
        decided_by: str | None = None,
    ) -> Diff:
        """委托给模块级 `resolve()` —— 状态机只实现一份（见其 docstring）。"""
        return resolve(
            self.diffs, diff_id, verdict, decided_at=decided_at, decided_by=decided_by
        )
