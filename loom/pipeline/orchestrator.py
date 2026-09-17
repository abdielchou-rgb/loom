"""编排层：一句话想法 → 完整 IR → 正文。

这是「叙事编译器」的主入口。整条链是**严格线性**的，没有循环依赖：

    idea
      │
      ├─ PremiseEngine     → L3 承诺层（主题 / 结局锚点 / 必要转折）
      ├─ CastEngine        → 卡司表（谁在这部戏里）
      ├─ StructureEngine   → L1 情节层 + 场景骨架（含 McKee 价值翻转硬约束）
      ├─ CharacterEngine   → L2 角色层 + 世界层（此时能看到场景了）
      ├─ LoreSeeder        → 记忆层（常驻 / 关键词触发 / 递归激活）
      ├─ LedgerSeeder      → 悬念台账 + 知情矩阵
      ├─ TensionSeeder     → 张力点（**向前看**：接下来可以写什么）
      │
      └─ Scripter × N      → 逐场正文（只注入相关 lore，绝不注入全文）
            │
            └─ CriticLoop  → 体检 → 只自动修文风类；结构类转 Diff 提案

设计要点（来自 v2 调研的硬结论）：

  1. **控制点越靠上游越好**。人在回路的确认点设在 IR 层，不在文本层 ——
     改结构比改一万字便宜两个数量级。
  2. **生成与修订分离**。Critic 可以用不同模型，避免自我确认偏差。
  3. **只自动修「可自动修」的问题**。文风类（去 AI 味）自动改；
     结构类（承诺未兑现 / 谜题烂尾）不自动改 —— 自动改结构会毁掉作者的意图。
     但「留给人决策」必须有载体：结构类问题被转成 `Diff` 提案，
     作者用 `LoomPipeline.decide()` 一键采纳或拒绝，裁决进决策遥测。
  4. **正文阶段只注入相关记忆**。lore 按当前场景做关键词编译 + 预算封顶，
     而不是把设定集全文塞进上下文（那是长文失控的头号原因）。
  5. **「永不静默改写」是一条可机检的性质**，不是一个态度：
     `Diff.after` 在 `status` 变成 `accepted` 之前永远只是提案内容，
     而唯一能翻转 `status` 的入口是 `decide()` / `NarrativeIR.accept_proposal()`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..ir.enums import ArcShape, ChunkOrigin, Medium
from ..ir.models import (
    Diff,
    NarrativeIR,
    Provenance,
    SceneNode,
)
from ..ir.proposal import DiffStatus
from ..llm.base import Generator, TokenLedger
from ..llm.prompts import PROSE
from ..provenance.telemetry import DecisionTelemetry
from ..validators.base import Report
from ..validators import run_all
from .engines import (
    CastEngine,
    CharacterEngine,
    CriticLoop,
    LedgerSeeder,
    LoreSeeder,
    PremiseEngine,
    Proposer,
    Scripter,
    StructureEngine,
    TensionSeeder,
)


# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    ir: NarrativeIR
    report: Report
    log: list[str] = field(default_factory=list)
    ledger: TokenLedger | None = None
    #: 决策遥测（提案采纳率 + 来源/去向/字段分布）。无裁决时为全零，不是 None ——
    #: 「还没人裁决」和「没有遥测」是两件事，混在一起会让仪表盘显示不出来。
    telemetry: DecisionTelemetry = field(default_factory=DecisionTelemetry)

    @property
    def health(self) -> int:
        return self.report.score()

    def summary(self) -> str:
        ir = self.ir
        lines = [
            f"《{ir.title}》  {ir.medium.value} / {ir.commitment.arc_shape.value}",
            f"  场景 {len(ir.scenes)}  谜题 {len(ir.enigmas)}  事实 {len(ir.facts)}"
            f"  角色 {len(ir.characters.characters)}  lore {len(ir.lore.entries)}",
            f"  正文 {ir.word_count()} 字   IR 指纹 {ir.fingerprint()}",
            f"  结构健康分 {self.health}/100"
            f"（错 {len(self.report.errors)} · 警 {len(self.report.warnings)}"
            f" · 提示 {len(self.report.infos)}）",
        ]
        if ir.tension_points:
            lines.append(
                f"  张力点 {len(ir.tension_points)}（**向前看**：接下来可以写什么）"
            )
        if ir.proposals:
            pending = len(ir.pending_proposals())
            lines.append(
                f"  结构提案 {len(ir.proposals)}（待裁决 {pending}，"
                f"**不自动应用**）"
            )
        if self.ledger:
            lines.append("  " + self.ledger.render().replace("\n", "\n  "))
        return "\n".join(lines)


# ---------------------------------------------------------------------------


class LoomPipeline:
    """把六个引擎串成一条可运行的流水线。

    所有引擎都通过注入的 `Generator` 工作。默认是离线的 `MockGenerator`，
    换成 `LiteLLMGenerator` 即可接真模型 —— 下游代码零改动。
    """

    def __init__(
        self,
        gen: Generator,
        *,
        reviser: Generator | None = None,
        ledger: TokenLedger | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> None:
        self.gen = gen
        # Critic 默认复用同一个生成器；接真模型时建议传入不同模型
        self.reviser = reviser or gen
        self.ledger = ledger
        self.on_step = on_step
        self.log: list[str] = []
        # 决策遥测：记录「作者信不信任 AI 的提案」。纯内存、不取时钟。
        self.telemetry = DecisionTelemetry()

    # -- 内部 --

    def _step(self, msg: str) -> None:
        self.log.append(msg)
        if self.on_step:
            self.on_step(msg)

    # -- 阶段 A：想法 -> IR --

    def build_ir(
        self,
        idea: str,
        *,
        title: str | None = None,
        medium: Medium = Medium.NOVEL,
        arc_shape: ArcShape = ArcShape.MAN_IN_A_HOLE,
        template_id: str = "save_the_cat",
        scene_count: int = 5,
        target_length: int = 180000,
    ) -> NarrativeIR:
        if not idea or not idea.strip():
            raise ValueError("想法不能为空")

        # 1. 前提 -> 承诺层
        commitment = PremiseEngine(self.gen).run(
            idea,
            medium=medium,
            arc_shape=arc_shape,
            template_id=template_id,
            target_length=target_length,
        )
        self._step(
            f"前提：{commitment.logline[:40]}… "
            f"（{len(commitment.commitments)} 条承诺）"
        )

        # 2. 卡司表
        roster = CastEngine(self.gen).run(commitment)
        char_ids = [c["id"] for c in roster] or ["protagonist"]
        self._step(f"卡司：{', '.join(c['name'] for c in roster)}")

        # 3. 结构 -> 情节层 + 场景骨架
        plot, scenes = StructureEngine(self.gen).run(
            commitment,
            char_ids,
            names={c["id"]: c["name"] for c in roster},
            template_id=template_id,
            scene_count=scene_count,
        )
        flips = sum(1 for s in scenes if s.value_flips)
        self._step(
            f"结构：{len(scenes)} 场，价值翻转 {flips}/{len(scenes)}，"
            f"事件 {len(plot.events)}，因果链 {len(plot.links)}"
        )

        # 4. 角色层 + 世界层（此时能看到场景）
        characters, bible = CharacterEngine(self.gen).run(commitment, scenes)
        self._step(
            f"角色：{len(characters.characters)} 人，"
            f"行动元 {len(characters.actants)}，世界规则 {len(bible.rules)}"
        )

        # 5. 组装 IR
        ir = NarrativeIR(
            title=title or _title_from(idea),
            medium=medium,
            target_length=target_length,
            bible=bible,
            plot=plot,
            characters=characters,
            commitment=commitment,
            scenes=scenes,
            beat_template=template_id,
        )

        # 6. 记忆层
        ir.lore = LoreSeeder().run(ir)
        self._step(
            f"记忆层：{len(ir.lore.entries)} 条 "
            f"（常驻 {sum(1 for e in ir.lore.entries.values() if e.is_constant)}）"
        )

        # 7. 台账层
        ir.enigmas, ir.facts = LedgerSeeder().run(ir)
        self._step(
            f"台账：谜题 {len(ir.enigmas)}"
            f"（已解 {sum(1 for e in ir.enigmas if e.resolved_at_scene)}）"
            f"，事实 {len(ir.facts)}"
        )

        # 8. 张力层（**向前看**）—— 从锚（wound / lie）与信念层派生
        #    「接下来可以写什么」。放在最后：它消费的是前面所有层的结果。
        ir.tension_points = TensionSeeder().run(ir)
        if ir.tension_points:
            top = ir.top_tensions(1)[0]
            self._step(
                f"张力：{len(ir.tension_points)} 点"
                f"（最强 {top.type.value} {top.intensity:.2f}）"
            )
        return ir

    # -- 阶段 B：IR -> 正文 --

    def write(
        self,
        ir: NarrativeIR,
        *,
        words_per_scene: int = 800,
        skip_existing: bool = True,
    ) -> NarrativeIR:
        scripter = Scripter(self.gen)
        prev_tail = ""
        for s in ir.ordered_scenes():
            if skip_existing and s.prose:
                prev_tail = s.prose
                continue
            scripted = scripter.run(
                ir, s, target_words=words_per_scene, prev_tail=prev_tail
            )
            prose = scripted.prose
            s.prose = prose
            # ① CHANGES：自申报回流到场景节点（声明只是提示通道，不是真值通道）
            if scripted.declared:
                s.declared = scripted.declared
                s.declaration_raw = scripted.raw
            # 溯源：合规必需（AI 生成须显著标识）
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
                    char_count=len(prose),
                )
            )
            prev_tail = prose
        self._step(
            f"正文：{ir.word_count()} 字 / {len(ir.scenes)} 场"
            f"（{ir.word_count() // max(1, len(ir.scenes))} 字每场）"
        )
        return ir

    # -- 阶段 C：体检 + 修订 --

    def critique(self, ir: NarrativeIR, *, max_rounds: int = 2) -> tuple[NarrativeIR, Report]:
        loop = CriticLoop(self.reviser, max_rounds=max_rounds)
        ir, log = loop.run(ir)
        for line in log:
            self._step(line)
        return ir, run_all(ir)

    # -- 阶段 D：裁决（「永不静默改写」的唯一生效入口）--

    def decide(
        self,
        ir: NarrativeIR,
        diff_id: str,
        *,
        accept: bool = True,
        decided_at: str | None = None,
        decided_by: str | None = None,
        story_at: str | None = None,
    ) -> Diff:
        """裁决一条结构提案，并把这次裁决记入决策遥测。

        **这是提案生效的唯一入口。** 不调用它，`Diff.after` 永远不会变成
        「已生效的值」—— 这正是「永不静默改写」可以被机器检查的含义：
        不是承诺「我们不乱改」，而是**没有任何代码路径能在不经过这里的情况下
        把提案写进目标卡**。

        ── 两个时间，两个用途，别混 ──────────────────────────────
            `decided_at`  **墙钟**时刻（ISO 8601）→ 写进 `Diff.decided_at`。
                          这是**举证**用的：申诉时要证明「人在某时刻做了判断」。
            `story_at`    **故事内**时点标签（如「第 3 章」）→ 进遥测。
                          这是**调参**用的：看哪几章的提案最常被采纳。

        两者都由调用方传入，本方法**不取时钟** —— 取 `now()` 的结构写不出
        确定性测试，而一个测不准的采纳率会被当成噪声忽略掉，指标就退化回
        「靠感觉」了。

        `decided_by` 同理不默认填 "human"：谁裁的誰填，机器代裁就写机器，
        否则采纳率会被机器自己裁自己的案子灌水。

        先接受再拒绝 → `conflicted`。这不是异常，是要被**记录下来**的信号，
        因此它会照常进遥测（计入分母，见 `DecisionTelemetry.accept_rate`）。
        """
        fn = ir.accept_proposal if accept else ir.reject_proposal
        diff = fn(diff_id, decided_at=decided_at, decided_by=decided_by)
        self.telemetry.record(diff, story_at=story_at)
        self._step(
            f"提案 {diff.id} → {diff.status.value}"
            f"（已裁决 {self.telemetry.decisions} 次，"
            f"采纳率 {self.telemetry.accept_rate:.0%}）"
        )
        return diff

    def decide_all(
        self,
        ir: NarrativeIR,
        *,
        accept: bool,
        decided_at: str | None = None,
        decided_by: str | None = None,
        story_at: str | None = None,
    ) -> list[Diff]:
        """对当前**全部待裁决**提案一次性给出同向裁决。

        这是「一键采纳」的实现。注意它只在**显式调用**时发生 ——
        没有任何自动路径会走到这里。

        批量裁决共用同一个 `decided_at`：**它们是同一次操作**，
        逐条取时钟反而会让「作者第几次操作」这个事实消失。
        """
        return [
            self.decide(
                ir,
                d.id,
                accept=accept,
                decided_at=decided_at,
                decided_by=decided_by,
                story_at=story_at,
            )
            for d in ir.pending_proposals()
        ]

    # -- 一键全流程 --

    def run(
        self,
        idea: str,
        *,
        words_per_scene: int = 800,
        max_rounds: int = 2,
        **build_kwargs: Any,
    ) -> PipelineResult:
        ir = self.build_ir(idea, **build_kwargs)
        self.write(ir, words_per_scene=words_per_scene)
        ir, report = self.critique(ir, max_rounds=max_rounds)
        return PipelineResult(
            ir=ir,
            report=report,
            log=list(self.log),
            ledger=self.ledger,
            telemetry=self.telemetry,
        )


# ---------------------------------------------------------------------------


def _title_from(idea: str, limit: int = 12) -> str:
    """从想法里取一个短标题（真模型会自己起名，这里只做兜底）。"""
    cleaned = idea.strip().rstrip("。.!！?？")
    for sep in ("，", ",", "。", "；", ";", "——"):
        cleaned = cleaned.split(sep)[0]
    return (cleaned[:limit] or "未命名").strip()
