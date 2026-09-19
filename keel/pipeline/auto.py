"""自动驾驶：推进 IR，不是续写文本。

用户要求（原话）：「在我不喊停的时候，根据初始设计自动写作」。

**这句话里有一个必须消掉的歧义。** 若「自动写作」= 自动续写文本，则违反铁律 1
（IR 是产品本体）：IR 静止不动而文本一路变长，几场之后 IR 就成了一份过期的装饰，
校验器还在认真地检查一份虚构 —— 门禁全绿，查的是假货。

所以本模块的实现是**自动推进 IR**：每一轮产出一张场景卡 + 正文，然后把
`state_deltas` 提交回 IR，让 IR 始终是真值。文本只是这一轮的输出。

── 三个「不靠人」的地方，必须有机器自己的判据 ──────────────────

用户说「我不喊停就一直写」。但**自动驾驶的意义恰恰是人不在旁边看**，
所以「等用户喊停」不是停止条件，是侥幸。本模块的停止判据全部从 IR 派生：

  1. `target_scenes` 达标
  2. 结局锚点兑现（最后一场的结构字段与 `ending_anchor` 有字面重叠）
  3. 预算闸（场数 / token / 成本 / 时长）—— 没有它，「不喊停」就是失控
  4. **暂停**（不是停止）：结构类校验失败 / 漂移检测报警

> **曾有的第 2 条「全部承诺已兑现」已删除。** 理由见 `_commitments_done`
> 旧址（约第 385 行）的说明：承诺的 `satisfied` 是个**声明式**字段，
> 引擎不该猜它；而按 `must_hold_at` 派生停止条件在增量路径上恒真。
> 删掉一个恒真或恒假的判据，不是少了个功能，是少了个假功能。

第 5 条对应已定的自主度 **B**：机器自动出场景卡 + 正文，**每个结构决策留痕为
提案**，结构类校验失败**暂停等人**，绝不静默自动改结构（那会毁掉作者意图）。

── 决策留痕同时是合规资产 ──────────────────────────────────────

项目记忆里标着一个「待补」缺口：台账现在记的是**免责证据**（AI 参与了哪一场），
而申诉真正需要的是**主张证据**（人类做了哪些判断）。本模块把每一次结构决策
（追加哪一场、为什么）记成 `Diff` 提案 + 决策日志 —— 这正好就是那份主张证据。
**带留痕的自动驾驶产出的合规证据，比人手写的更硬**：随手写的故事里
「人判断了什么」不可回放，而这里每个结构决策都是可回放的记录。

── 起飞前体检 ──────────────────────────────────────────────────

自主性会**放大初始设计的质量**：计划弱，自动驾驶会忠实地、大规模地执行一个
坏计划 —— 不是写出烂故事，是写出很长很长的烂故事，且每场都「看起来挺合理」。
所以本模块在开跑前先 `preflight` 那份计划，有 blocker 就拒绝起飞。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..ir.enums import (
    ArcShape,
    ChunkOrigin,
    Focalization,
    Frequency,
    Medium,
    SceneOutcome,
    Severity,
)
from ..ir.models import (
    CausalLink,
    Diff,
    Effect,
    EventNode,
    NarrativeIR,
    Precondition,
    Provenance,
    SceneNode,
    StateDelta,
    TimePoint,
)
from ..ir.proposal import DiffStatus
from ..clock import wall_iso
from ..llm.prompts import PROSE
from ..validators.base import Finding, Report, run_all
from ..validators.drift import drift_guard
from .budget import Budget, BudgetExceeded, Usage, check, render as render_budget
from .checkpoint import RunState, save as save_checkpoint, resume as resume_checkpoint
from .engines import Scripter
from .memory import NarrativeMemory
from .orchestrator import KeelPipeline
from .preflight import PreflightError, preflight

#: 停止原因。**显式枚举，不要散成字符串** —— 停止原因是给人看的诊断，
#: 「为什么它停了」必须是可回答的问题，否则自动驾驶在用户眼里就是随机的。
#:
#: 注：曾有 `STOP_COMMITMENTS = "commitments_satisfied"`，已删除 ——
#: 它在增量路径上恒真。理由见 `_commitments_done` 旧址。
STOP_TARGET = "target_reached"
STOP_ANCHOR = "ending_anchor_reached"
STOP_BUDGET = "budget_exceeded"
STOP_PAUSED_STRUCTURAL = "paused_structural"
STOP_PAUSED_DRIFT = "paused_drift"

#: **收尾型**校验码：它们判断的是「到结束时兑现了没有」，
#: 因此在跑到终点之前**必然**是未兑现状态。
#:
#: 把它们当作「结构坏了」去暂停，自动驾驶会在第 2 场就停下 ——
#: 因为弧线闭合、承诺兑现这类性质，按定义只能在结尾成立。
#: 区分「机器现在正在跑偏」与「稿子还没写完」是这套判据的全部意义：
#: 前者要暂停（否则一路跑到底全是废话），后者只是未完稿的正常状态。
#:   * `commitment_satisfied`     承诺兑现 —— 兑现它正是这一趟跑的目的
#:   * `lie_arc_closure`          lie 要被打破，那发生在后半程/高潮
#:   * `need_revelation_at_climax` 自我启示发生在高潮，不是第 2 场
#:   * `causal_chain_integrity`   未完稿的**最后一场**必然是孤立事件
#:   * `provenance_coverage`      自动驾驶下 AI 占比恒为 100%，是已接受
#:     定位（「AI 替你写，溯源必须诚实」）的必然后果
#:
#: **它们没有被消音**：全部照常出现在最终体检报告与合规输出里。
#: 真正会触发暂停的是**进行中的**结构破损（实体未登记、时间线回退等）——
#: 那些是「现在就已经错了」，不是「还没写完」。
_CLOSURE_CODES = frozenset(
    {
        "commitment_satisfied",
        "lie_arc_closure",
        "need_revelation_at_climax",
        "causal_chain_integrity",
        "provenance_coverage",
    }
)


@dataclass
class AutoConfig:
    """自动驾驶的运行参数。

    `budget` 默认给一个场数上限。**没有预算的「一直写」是失控**，
    不是功能 —— 这是本模块唯一的硬安全边界。
    """

    target_scenes: int = 6
    words_per_scene: int = 300
    budget: Budget = field(default_factory=lambda: Budget(max_scenes=6))
    #: B 模式：结构类校验失败就暂停（True），而不是继续写下去。
    pause_on_structural: bool = True
    pause_on_drift: bool = True
    #: 每场都落检查点。长跑里「崩在第 47 场要能从 47 续」，重跑是不可接受的。
    checkpoint_every: int = 1


@dataclass
class AutoResult:
    ir: NarrativeIR
    report: Report
    stop_reason: str
    scenes_written: int
    decisions: list[dict] = field(default_factory=list)
    paused: bool = False
    pause_findings: list[Finding] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


#: 暂停时落在检查点目录里的**人工可编辑副本**。
#: 它不是第二个真值，只是一个锚：提醒「这里有一份等你裁决的 IR」。
PAUSED_IR_NAME = "paused.json"


def _decided_count(ir: NarrativeIR) -> int:
    """已裁决提案数。判断「人动过这份 IR 没有」的最小充分信号。

    为什么不用文本 diff 或文件 mtime：mtime 会被任何一次复制/同步改写
    （「拷贝了一下」≠「做了判断」），而**已裁决提案数只会被人的裁决改变**
    —— 它测的正是我们要测的那件事。
    """
    return sum(1 for d in ir.proposals if d.status is not DiffStatus.PENDING)


def _entry_for(diff: Diff, *, kind: str | None = None) -> dict:
    """一条提案 → 一条台账记录。

    台账**从 IR 派生**，而不是自己另存一份：两份必然漂移，而漂移的方向
    永远是「台账比 IR 好看」—— IR 里那条还是 pending，台账上却写着
    「已驳回」，于是举证时拿出来的是一份与稿子对不上的记录。
    """
    decided = diff.status is not DiffStatus.PENDING
    return {
        "kind": kind or ("human_verdict" if decided else "machine_proposal"),
        "diff_id": diff.id,
        "scene_id": (
            diff.target_card.split(":", 1)[-1] if ":" in diff.target_card else None
        ),
        "status": diff.status.value,
        "rationale": diff.rationale,
        "proposed_at": diff.proposed_at,
        "proposed_by": diff.source_card,
        "decided_at": diff.decided_at,
        "decided_by": diff.decided_by,
    }


def _decision_entries(ir: NarrativeIR) -> list[dict]:
    """整份台账 = 全部提案的记录（已裁决的标 `human_verdict`）。

    人工裁决发生在 Keel 进程之外（作者用 `keel decide` 改的是 IR），
    所以续跑时必须把那些裁决**读回来**补进台账 —— 不补，续跑后的
    decisions.json 会少掉「人驳回过哪些」这段，而这正是这份台账
    唯一真正有价值的那一段。
    """
    return [_entry_for(d) for d in ir.proposals]


def _shingles(text: str, n: int = 2) -> set[str]:
    """字符二元组。中文没有词边界，字符 bigram 是零依赖的近似。

    与 `validators/narrative.py` 里的同名私有函数一致 —— 那里是私有的，
    跨模块 import 私有符号会让校验层反向成为流水线的依赖（铁律 14 的镜像：
    跨层共用的东西该上移，而不是反向引用）。
    """
    t = "".join(ch for ch in text if not ch.isspace())
    return {t[i : i + n] for i in range(len(t) - n + 1)} if len(t) >= n else set()


def _build_scene(raw: dict[str, Any], index: int, fallback_focalizer: str) -> SceneNode:
    """把 `next_scene` 的输出落成 SceneNode。

    与 `StructureEngine` 的解析保持一致的两点（这两点历史上都出过 bug）：
      * `state_deltas` 认**数组**（一场常有多人改变，只申报一个会让其余变成
        「正文改了、卡片没写」—— 正是 `declaration_consistency` 要抓的漏报）
      * 时间标记没有就留 `None`（渲染器据此省略，而不是给整部戏盖一层假夜色）
    """
    sid = str(raw.get("id") or f"sc{index}")
    focalizer = str(raw.get("focalizer") or fallback_focalizer)

    deltas: list[StateDelta] = []
    raw_deltas = raw.get("state_deltas")
    if raw_deltas is None:
        raw_deltas = raw.get("state_delta")
    items = (
        raw_deltas
        if isinstance(raw_deltas, list)
        else ([raw_deltas] if isinstance(raw_deltas, dict) else [])
    )
    for one in items:
        if not (isinstance(one, dict) and one.get("entity_id")):
            continue
        try:
            deltas.append(
                StateDelta(
                    entity_id=str(one["entity_id"]),
                    attribute=str(one.get("attribute", "state")),
                    before=one.get("before", False),
                    after=one.get("after", True),
                )
            )
        except Exception:
            continue

    vcs = str(raw.get("value_charge_start", "+"))
    vce = str(raw.get("value_charge_end", "-"))
    if vcs == vce:  # 强制 McKee 约束：保证价值翻转
        vce = "-" if vcs == "+" else "+"

    try:
        outcome = SceneOutcome(str(raw.get("outcome", "yes_but")))
    except ValueError:
        outcome = SceneOutcome.YES_BUT

    label = str(raw["time_label"]).strip() if raw.get("time_label") else None

    return SceneNode(
        id=sid,
        title=str(raw.get("title") or f"第 {index} 场"),
        focalizer=focalizer,
        narrator=focalizer,
        focalization=Focalization.INTERNAL,
        fabula_time=TimePoint(
            day=int(raw.get("fabula_day", index - 1)),
            label=label or None,
        ),
        sjuzhet_index=index - 1,
        frequency=Frequency.SINGULATIVE,
        value=str(raw.get("value", "代价")),
        value_charge_start=vcs if vcs in "+-" else "+",  # type: ignore[arg-type]
        value_charge_end=vce if vce in "+-" else "-",  # type: ignore[arg-type]
        goal=str(raw.get("goal") or ""),
        conflict=str(raw.get("conflict") or ""),
        turning_point=str(raw.get("turning_point") or ""),
        outcome=outcome,
        entities=[focalizer],
        location=raw.get("location"),
        emotion=float(raw.get("emotion", 0.0)),
        state_deltas=deltas,
    )


class AutoWriter:
    """自动驾驶写作者。

    与 `KeelPipeline.run` 的区别：`run` 是一次性的（建 IR → 写正文 → 体检），
    本类是**增量**的（建计划 → 一场一场推进 IR → 每轮体检 → 到判据停）。
    两者契约不同，所以是独立入口，不是 `run` 的一个参数。
    """

    def __init__(
        self,
        gen,
        *,
        ledger=None,
        on_step: Callable[[str], None] | None = None,
        cfg: AutoConfig | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.gen = gen
        self.ledger = ledger
        self.on_step = on_step or (lambda m: None)
        self.cfg = cfg or AutoConfig()
        #: 取时刻的函数。**注入而非内置**，这样测试能给出确定的时间戳
        #: （举证字段测不准 = 这条证据在测试里永远验不到）。
        self.clock = clock or (lambda: wall_iso())
        self.log: list[str] = []

    def _step(self, msg: str) -> None:
        self.log.append(msg)
        self.on_step(msg)

    # -- 停止判据（全部从 IR 派生）--------------------------------------

    @staticmethod
    def _append_event(ir: NarrativeIR, scene: SceneNode, ids: list[str]) -> None:
        """把新场景登记为情节事件，并**连进因果链**。

        不建这条链，每一场都是孤立事件 —— 那不是「还没写完」，那是
        「一场接一场却互不相干」，正是本项目存在的理由所要防的失败模式。
        """
        # `plot.events` 是 dict（id -> EventNode），迭代拿到的是键不是节点。
        prev = [e for e in ir.plot.events.values() if e.scene_id]
        ev = EventNode(
            id=f"ev_{scene.id}",
            summary=scene.turning_point,
            scene_id=scene.id,
            participants=[scene.focalizer] + [i for i in ids if i != scene.focalizer],
            location=scene.location,
            preconditions=(
                [Precondition(kind="prior_event", target=prev[-1].id)] if prev else []
            ),
            effects=[Effect(kind="reveal", target=scene.focalizer)],
            surprise=round(abs(scene.emotion), 2),
        )
        ir.plot.add_event(ev)
        if prev:
            ir.plot.links.append(
                CausalLink(src=prev[-1].id, dst=ev.id, kind="enables")
            )

    def _anchor_reached(self, ir: NarrativeIR) -> bool:
        """结局锚点是否已被最后一场兑现。

        字面判据（与 `lie_arc_closure` 同一取舍）：认不出同义改写，
        但「锚点写了却没人去写它」是最常见的跑偏，值得一查。
        """
        anchor = (ir.commitment.ending_anchor or "").strip()
        scenes = ir.ordered_scenes()
        if not anchor or not scenes:
            return False
        tail = " ".join(
            f"{s.turning_point} {s.goal} {s.value}" for s in scenes[-2:]
        )
        return bool(_shingles(anchor) & _shingles(tail))

    # ── 已删除：`_refresh_commitments` 与 `_commitments_done` ──────────
    #
    # 这两个方法一起构成曾经的停止判据 #2「全部承诺已兑现」。它们被删掉，
    # 不是因为它跑不通，而是因为**它不可能跑对**。两条独立理由：
    #
    # **理由一：`satisfied` 是声明式字段，引擎不该猜它。**
    #   曾经这里调 `_commitment_evident` 做词法匹配来「算」兑现与否。
    #   实测证明那个判据在中文上**恒假**：它把整句中文切成**一个** token
    #   （`「信任不是一种判断」`），而正文永远不可能逐字复现整句。
    #   后果是 `commitment_satisfied` 对着正常故事开火（7/7 误报，
    #   `scripts/pipeline_demo.py` 健康分 92 → 21）。
    #   `satisfied` 现在只由**声明**驱动（默认 False），引擎不再代劳。
    #
    # **理由二：按 `must_hold_at` 派生的停止条件在增量路径上恒真。**
    #   `_bind_commitments` 按「第几场 / 共几场」的**比例**铺锚点，而
    #   `AutoWriter` 在第一场刚建好时就来绑 —— 此时场景列表长度为 1，
    #   于是**全部 7 条承诺都落到 `sc1`**。实测：写满第 1 场后
    #   「全部承诺已兑现」立刻为真，整条自动运行在第 1 场就停了。
    #   若改成按计划跨度铺开，则最后一条承诺的锚点落在计划末场，
    #   停止时刻与 `target_scenes` **完全重合** —— 那是个冗余判据，
    #   不是独立判据。
    #
    # 恒真的判据与恒假的判据一样没用，而冗余判据会让人以为有两个
    # 独立的收敛信号。删掉它，收敛信号诚实地只剩三个（场数 / 锚点 / 预算）。
    #
    # 保留下来的东西：`CommitmentLayer.satisfied` 仍在（声明式），
    # 仍被 `validators/drift.py` 的论点面与 `pipeline/preflight.py`
    # 消费；只是**没有任何引擎再替作者填它**。

    # -- 主循环 ----------------------------------------------------------

    def run(
        self,
        idea: str,
        *,
        medium: Medium = Medium.NOVEL,
        arc_shape: ArcShape = ArcShape.MAN_IN_A_HOLE,
        template_id: str = "save_the_cat",
        checkpoint_dir: Path | None = None,
        resume_ir: Path | None = None,
    ) -> AutoResult:
        cfg = self.cfg
        usage = Usage(started_at=time.time())
        decisions: list[dict] = []

        # 1. 计划（+ 第一张场景卡）。自动驾驶从「一份可检验的计划」出发，
        #    不是从一片空白出发 —— 空白的计划无法派生任何停止判据。
        pipe = KeelPipeline(self.gen, ledger=self.ledger, on_step=self._step)
        ir = pipe.build_ir(
            idea,
            medium=medium,
            arc_shape=arc_shape,
            template_id=template_id,
            scene_count=1,
        )

        # 自动驾驶开跑时，「承诺已兑现」在语义上**必为假** —— 一个字都还没写。
        # P0.5 已修：_bind_commitments 不再无条件设 satisfied=True，
        # 兑现判定改为基于场景结构字段的可解释匹配（validators/structure.py）。
        for c in ir.commitment.commitments:
            c.satisfied = False

        # P1 动态叙事记忆：从 IR 恢复（续跑）或新建。
        # 记忆与 lore 的边界：lore = 世界知识（常驻/触发），
        # memory = 叙事状态（随场推进）。两者不合并。
        memory = (
            NarrativeMemory.from_json(ir.memory_json)
            if ir.memory_json
            else NarrativeMemory()
        )

        # 2. 起飞前体检：**自主性会放大计划的质量**，计划不合格不许上路。
        pf = preflight(ir)
        if not pf.ok:
            raise PreflightError(
                "计划未通过起飞前体检，拒绝进入自动驾驶：\n"
                + "\n".join(f.render() for f in pf.blockers)
            )
        self._step(f"起飞前体检通过（{pf.checks_run} 项检查）")

        # 3. 续跑：有检查点就从检查点接上（长跑崩了不该重头再来）
        #
        # 3a. **人类裁决优先于检查点。** 检查点存的是「机器跑到哪了」，
        #     人在暂停期间做的裁决不在里面 —— 若直接拿检查点覆盖，
        #     作者刚驳回的提案会复活成 pending，那次驳回连痕迹都不留。
        #     「人裁完了又被机器覆盖」正是本模块存在的理由要防的事，
        #     所以显式给了 `resume_ir` 就无条件采用它（那是人的最新真值）。
        human_adopted = False
        if resume_ir is not None:
            try:
                ir = NarrativeIR.from_json(Path(resume_ir).read_text(encoding="utf-8"))
                decisions = _decision_entries(ir)
                usage = Usage(started_at=time.time())
                human_adopted = True
                self._step(
                    f"从人工修订版续跑：{resume_ir}"
                    f"（{_decided_count(ir)} 条人类裁决已读回台账，"
                    f"共 {len(ir.proposals)} 条提案）"
                )
            except Exception as exc:  # 读不出来要吭声，然后退回常规续跑
                self._step(f"⚠ 人工修订版读不出来（{exc}），改为从检查点续跑")
                human_adopted = False
        elif checkpoint_dir is not None and (checkpoint_dir / PAUSED_IR_NAME).exists():
            # 有人工修订版却没指定 → 必须是**响亮的警告**，不能是静默的选择。
            self._step(
                f"⚠ 检查点目录里有 {PAUSED_IR_NAME}，但你没有指定 --resume-from；"
                "本次从检查点续跑，**你在那里的裁决不会被继承**。"
            )

        if checkpoint_dir is not None:
            state = resume_checkpoint(
                checkpoint_dir, idea, {"medium": medium.value, "template": template_id}
            )
            if human_adopted:
                # 检查点**必须让位**：它比人工修订版旧，采用它就是覆盖人的判断。
                # 这里不进 if 分支不是「省一次 IO」，是语义要求 ——
                # 只把 usage 之外的东西留给检查点，IR 与台账一律不碰。
                self._step(
                    f"检查点跳过：人工修订版优先"
                    f"（检查点停在 {state.completed_scenes} 场，以人那份为准）"
                )
            elif state.completed_scenes > 0 and state.ir_json:
                try:
                    ir = NarrativeIR.from_json(state.ir_json)
                    decisions = list(state.decisions)
                    usage = Usage(**{**Usage().__dict__, **state.usage})
                    self._step(f"续跑：从第 {state.completed_scenes + 1} 场接上")
                except Exception as exc:  # 检查点坏了要**吭声**，不能静默重来
                    self._step(f"⚠ 检查点无法还原（{exc}），从计划重新开跑")

        scripter = Scripter(self.gen)
        stop = ""
        paused = False
        pause_findings: list[Finding] = []

        while True:
            # -- 预算闸：每一轮开始前查，硬停 --
            try:
                check(cfg.budget, usage, now=time.time())
            except BudgetExceeded:
                stop = STOP_BUDGET
                self._step(f"预算闸触发，停止：{render_budget(cfg.budget, usage)}")
                break

            # -- 写正文：给所有还没正文的场景写 --
            prev_tail = ""
            for s in ir.ordered_scenes():
                if s.prose:
                    prev_tail = s.prose
                    continue
                scripted = scripter.run(
                    ir, s, target_words=cfg.words_per_scene, prev_tail=prev_tail
                )
                s.prose = scripted.prose
                if scripted.declared:
                    s.declared = scripted.declared
                    s.declaration_raw = scripted.raw
                # 溯源：合规必需。自动驾驶只会让 AI 占比更高，
                # 所以**逐场**留痕比以往更重要（这也是「溯源诚实」的落地点）。
                s.origin = ChunkOrigin.AI_GENERATED
                s.model_id = self.gen.model_id
                s.prompt_version = getattr(PROSE, "version", None)
                ir.provenance.append(
                    Provenance(
                        chunk_id=f"chunk_{s.id}",
                        scene_id=s.id,
                        origin=ChunkOrigin.AI_GENERATED,
                        model_id=self.gen.model_id,
                        prompt_version=s.prompt_version,
                        char_count=len(s.prose),
                    )
                )
                usage.scenes += 1
                prev_tail = s.prose
                self._step(f"正文：{s.title}（{len(s.prose)} 字）")

            # P1 动态叙事记忆：每写完一场就把 state_deltas 提交进记忆，
            # 后续场只注入**与当前相关**的记忆（沿用 Scripter「只注入相关
            # lore，绝不注入全文」的既有纪律）。记忆进 IR，可持久化、可重跑。
            for s in ir.ordered_scenes():
                if s.prose and s.state_deltas:
                    memory.commit(s)
            ir.memory_json = memory.to_json()

            # 承诺的 `satisfied` 不再由引擎代填 —— 它是声明式字段，
            # 「主题兑现了没有」不可机判。见 `_refresh_commitments` 旧址。

            # -- 体检 --
            report = run_all(ir)
            structural = [
                f
                for f in report.findings
                if f.severity in (Severity.ERROR, Severity.WARN)
                and f.code not in _CLOSURE_CODES
            ]

            # -- 漂移检测：现有校验器全是逐场局部的，只有它问「整体还在不在路上」 --
            drift = drift_guard(ir)
            if drift and cfg.pause_on_drift:
                paused = True
                pause_findings = drift
                stop = STOP_PAUSED_DRIFT
                self._step("漂移检测报警，暂停等人：")
                for f in drift:
                    self._step("  " + f.message)
                break

            if structural and cfg.pause_on_structural:
                paused = True
                pause_findings = structural
                stop = STOP_PAUSED_STRUCTURAL
                self._step(
                    f"结构类校验失败（{len(structural)} 条），暂停等人 —— "
                    "自动驾驶不自动改结构（那会毁掉作者意图）"
                )
                for f in structural[:5]:
                    self._step("  " + f.render())
                break

            # -- 停止判据（从 IR 派生）--
            # 只剩两个「提前收敛」信号 + 预算闸。曾经的「全部承诺已兑现」
            # 已删：它在增量路径上恒真（全部锚点落到 sc1），详见旧址说明。
            n = len(ir.scenes)
            if n >= cfg.target_scenes:
                stop = STOP_TARGET
                self._step(f"达到目标场数 {cfg.target_scenes}，停止")
                break
            if self._anchor_reached(ir):
                stop = STOP_ANCHOR
                self._step("结局锚点已兑现，停止")
                break

            # -- 下一场：结构决策（自动做，但**留痕为提案**）--
            names = {cid: c.name for cid, c in ir.characters.characters.items()}
            ids = list(names) or ["protagonist"]
            opens = [
                c.statement
                for c in ir.commitment.commitments
                if not c.satisfied
            ]
            payload = {
                "premise": ir.commitment.premise or "",
                "controlling_idea": ir.commitment.controlling_idea or "",
                "ending_anchor": ir.commitment.ending_anchor or "",
                "done_count": n,
                "prior": "\n".join(
                    f"- {s.title}：{s.turning_point}"
                    for s in ir.ordered_scenes()[-5:]
                )
                or "（这是第一场）",
                "open_commitments": opens,
                # P1：只注入**与当前相关**的记忆，绝不注入全文
                # （沿用 Scripter 对 lore 的既有纪律）。
                "memory": (
                    memory.brief_for(ir.ordered_scenes()[-1])
                    if ir.ordered_scenes()
                    else ""
                ),
                "characters": "、".join(names.values()) or "、".join(ids),
                "character_ids": ids,
                "character_names": names,
                "values": sorted({s.value for s in ir.scenes if s.value})
                or ["信任", "代价", "真相"],
                "index": n + 1,
                "target": cfg.target_scenes,
            }
            raw = self.gen.generate("next_scene", payload)
            scene = _build_scene(raw, n + 1, ids[0])
            ir.scenes.append(scene)

            # 因果链：新事件必须挂到前一个事件上，否则它会变成「孤立事件」
            # （`causal_chain_integrity` 会正确地指出这一点 —— 这是真缺陷，
            #   不是误报：一场接一场却没有因果，正是铁律 2 要防的东西）。
            self._append_event(ir, scene, ids)

            # 决策留痕：追加哪一场、依据是什么。这是 B 模式的核心约束
            # （结构决策自动做，但绝不静默），同时也补上「人类做了哪些判断」的
            # 主张证据缺口。
            rationale = (
                f"推进未兑现承诺 {len(opens)} 条，目标 {cfg.target_scenes} 场"
            )
            # `proposed_at`：机器**何时**提的案。人类裁决时会有 `decided_at`，
            # 两个时刻合起来才是完整的一次「机器提议 → 人类判断」证据链。
            # 只有前者没有后者 = 提案没人看；只有后者没有前者 = 来源不明。
            ir.proposals.append(
                Diff(
                    id=f"auto_n{n + 1}",
                    target_card=f"scene:{scene.id}",
                    field="append",
                    before=None,
                    after={
                        "title": scene.title,
                        "turning_point": scene.turning_point,
                        "value": scene.value,
                    },
                    rationale=rationale,
                    source_card=f"auto:{self.gen.model_id}",
                    proposed_at=self.clock(),
                )
            )
            decisions.append(_entry_for(ir.proposals[-1], kind="machine_proposal"))
            self._step(f"结构决策：追加第 {n + 1} 场「{scene.title}」")

            # -- 落检查点 --
            if checkpoint_dir is not None:
                save_checkpoint(
                    RunState(
                        run_id="auto",
                        idea=idea,
                        params={"medium": medium.value, "template": template_id},
                        completed_scenes=len(ir.scenes),
                        ir_json=ir.to_json(),
                        decisions=decisions,
                        usage={
                            "scenes": usage.scenes,
                            "tokens": usage.tokens,
                            "cost": usage.cost,
                        },
                    ),
                    checkpoint_dir,
                )

        if not stop:
            stop = STOP_TARGET

        if paused and checkpoint_dir is not None:
            # 暂停时落一份**人可以直接编辑**的 IR 副本。
            # 它是「等你裁决的东西」的物理锚点：暂停消息会指到它，
            # 续跑时 `--resume-from` 再把它读回来。没有它，人就只能在
            # 一堆同名 ir.json 里猜哪一份才是要改的那份。
            try:
                (checkpoint_dir / PAUSED_IR_NAME).write_text(
                    ir.to_json(), encoding="utf-8"
                )
            except OSError as exc:  # 落不下也要继续 —— 产物已经写在 outdir 了
                self._step(f"⚠ 人工修订副本写不下去（{exc}）")

        if paused:
            # 暂停本身要留痕：它是**机器主动把决定权交回给人**的时刻。
            # 事后回看，「机器在哪一步停了下来等人」正是判断自动驾驶是否
            # 越权的依据；不记，这趟跑在证据上就只剩「一路顺利」。
            decisions.append(
                {
                    "index": len(ir.scenes),
                    "kind": "pause",
                    "rationale": f"{stop}："
                    + "；".join(f.message for f in pause_findings[:3]),
                    "model": self.gen.model_id,
                    "proposed_at": self.clock(),
                    "proposed_by": f"machine:{self.gen.model_id}",
                    "decided_at": None,
                    "decided_by": None,
                    "awaiting_human": True,
                }
            )

        if self.ledger is not None:
            usage.tokens = getattr(self.ledger, "total_tokens", usage.tokens)

        return AutoResult(
            ir=ir,
            report=run_all(ir),
            stop_reason=stop,
            scenes_written=usage.scenes,
            decisions=decisions,
            paused=paused,
            pause_findings=pause_findings,
            log=list(self.log),
            usage=usage,
        )
