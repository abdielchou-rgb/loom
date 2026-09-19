"""投稿前合规自检 —— 把「平台会怎么看」变成一份可跑、可导出、可申诉的报告。

── 它是什么，不是什么 ─────────────────────────────────────────

**它是**：用与平台**同一套特征空间**如实告诉作者「你这稿子在哪些维度上
落在了机器的常见区间」，并给出**真的**改写方向；外加一份「哪些事 Keel
证明不了、必须你自己确认」的清单。

**它不是**：反检测。Keel 帮作者「真的写得更好」，不帮作者「看起来像人写的」。
后者是伪造，且技术上必然失败 —— 检测早已从词汇层转到叙事特征层，
表层改写（同义词替换、句式打乱）对付不了「情感锚点偏移率」这类指标。

── 三层结构（缺一层就是在骗人）──────────────────────────────

  A. 法律义务   AI 占比、溯源可证明性、标识义务。这几项**可机检**。
  B. 平台画像   平台公开口径里 Keel 能复现的那些维度。是**统计画像**，不是判决。
  C. 不可检声明 Keel 结构上**看不到**的维度（平台自有语料相似度、困惑度、
                账号行为特征、产物上到底有没有贴标识……）。

只出 A+B 而不出 C，会让作者以为「自检通过 = 不会被判 AI」。
那是一个 Keel 兑现不了的承诺 —— 平台判定用的信息 Keel 永远不全。
**C 层是本模块最重要的部分**，它把「不知道」显式化。

── 维度对照表的状态是**派生的**，不是手写的 ────────────────────

`DIMENSIONS` 里每一行写的只是「这个平台维度对应 Keel 的哪几个检查 code」，
**是否覆盖**由 `set(available())` 现算。理由与 `Proposer` 那处一致：
手写「✅ 已有 / ❌ 缺」必然漂移 —— 补一个检测器，表里它仍然是「❌ 缺」，
而没有任何机制会发现。手写的清单是**会过期的注释**，派生的清单是**事实**。

── 证据等级（必须写出来）────────────────────────────────────

平台的具体检测维度**没有被官方公开**。本模块用的维度清单来自媒体与
自媒体转述（起点「墨瞳」17 维、番茄 200+ 维）。
**方向可信（多个独立来源都指向「检测已转向叙事特征」），细节存疑。**
因此：

  * 阈值与维度名不得对外宣称「平台就是这么判的」；
  * 番茄的两条具体口径（章节字数 ±5%、一段 >4 次高频副词）**有明确出处**，
    可信度高于其余条目，在表里单独标注；
  * 平台改口径时，改的是 `DIMENSIONS` 与 `rhythm.py`，不是产品承诺。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from ..ir.enums import ChunkOrigin, Medium
from ..ir.models import NarrativeIR
from ..provenance.meter import ParticipationReport, ProvenanceLedger
from ..validators.base import Finding, Report, available, run_all
from .rhythm import scan_ir as scan_rhythm_ir

# ---------------------------------------------------------------------------
# 证据等级
# ---------------------------------------------------------------------------

#: 有明确公开出处（平台自己说过）。
E_PLATFORM = "平台公开口径"
#: 媒体/自媒体转述，非官方。方向可信、细节存疑。
E_REPORTED = "媒体转述（非官方）"
#: 法规条文。
E_LAW = "法规"

# ---------------------------------------------------------------------------
# A. 法律义务
# ---------------------------------------------------------------------------

#: 两层监管（**源与流**，不要混为一谈）：
#:
#:   《人工智能生成合成内容标识办法》（国信办通字〔2025〕2 号）2025-09-01 施行
#:       —— 标识义务的**源头**：显式标识 + 隐式标识（文件元数据须含
#:          生成合成属性、服务提供者名称或编码、内容编号）
#:   《微短剧发展管理办法》（国家广电总局令第 16 号）2026-09-01 施行
#:       第 34 条 —— 把上面的义务**落到微短剧场景**：AI 生成制作的微短剧，
#:       每集明显位置须加提示标识
#:
#: 之前项目文档把两者混成一条，写成「AI 参与须显著标识（微短剧办法）」——
#: 那会让 2025-09-01 就存在的义务看起来是 2026-09-01 才出现的。
REGULATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "《人工智能生成合成内容标识办法》",
        "国信办通字〔2025〕2 号 · 2025-09-01 施行",
        "显式标识 + 隐式标识（元数据：生成属性 / 提供者名称或编码 / 内容编号）",
    ),
    (
        "《微短剧发展管理办法》第 34 条",
        "国家广电总局令第 16 号 · 2026-09-01 施行",
        "AI 生成制作的微短剧，每集明显位置加提示标识",
    ),
)

#: 平台红线（2026 年 7–8 月口径）。
PLATFORM_LINES: tuple[tuple[str, str, str], ...] = (
    (
        "起点中文网",
        "AI 内容占比 >10% 即处理；纯 AI 正文属红线",
        "去流量化（移出榜单与推荐位）而非下架 · 2026-08-18 集中处置 27 本均订过万",
    ),
    (
        "番茄小说",
        "生成内容 >10% 触发处理；AI 正文明确禁止",
        "拒签 / 断推荐 / 封禁 · 2026-07 单月拒签 16 万本、下架 5.4 万部",
    ),
    (
        "晋江文学城",
        "仅允许校对级 / 元素级 / 梗概级三类辅助",
        "锁章 + 黄牌 + 永久禁榜",
    ),
)


@dataclass(frozen=True)
class Dimension:
    """一个平台检测维度 → Keel 的对应能力。

    `keel` 为空元组 = Keel 结构上不做这个维度（不是「还没做」，是做不了：
    例如平台自有语料相似度，Keel 没有那份语料）。
    """

    key: str
    platform: str
    keel: tuple[str, ...]
    evidence: str = E_REPORTED
    note: str = ""

    @property
    def covered(self) -> bool:
        """是否覆盖 —— **派生**，不是手写。

        能力名的两种形态都要认：
          * registry 里的校验器 code（`keel/validators/`）
          * `keel/audit/` 下**暴露 `scan_ir` 的模块名**（anti_slop / craft /
            dress / transportation / cognitive …）
            它们不在 registry 里（这是既有设计，见 `Proposer` 的说明），
            但它们是 Keel 真实拥有的能力。

        只认第一种会闹笑话：`dress.py` 明明量了风格漂移，对照表里却显示
        「Keel 不做」—— **派生口径取错，比手写清单更容易骗人**，
        因为它看起来是算出来的。所以两个来源都要扫，且都是现取。
        """
        if not self.keel:
            return False
        return set(self.keel) <= (_REGISTRY_CACHE | _AUDIT_CACHE)


_REGISTRY_CACHE: frozenset[str] = frozenset()
_AUDIT_CACHE: frozenset[str] = frozenset()


def _refresh_registry() -> None:
    """能力清单是运行时填充的，故每次自检前刷一次（导入顺序不可依赖）。"""
    global _REGISTRY_CACHE, _AUDIT_CACHE
    _REGISTRY_CACHE = frozenset(available())
    _AUDIT_CACHE = _audit_capabilities()


def _audit_capabilities() -> frozenset[str]:
    """`keel/audit/` 下所有暴露 `scan_ir` 的模块名 —— **扫包派生**，不手写。

    判据落在语义上（有没有 `scan_ir` 这个统一入口），不是语法上
    （是不是 .py 文件）—— 与 `verify.py` 数引擎时用「有没有 `run()`」
    是同一个教训：按文件计数会把数据模块也算成能力。
    """
    import importlib
    import pkgutil

    from .. import audit

    names: set[str] = set()
    for m in pkgutil.iter_modules(audit.__path__):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{audit.__name__}.{m.name}")
        except Exception:  # 某个模块坏了不影响整张表，但会在别处报错
            continue
        if hasattr(mod, "scan_ir"):
            names.add(m.name)
    return frozenset(names)


#: 平台检测维度对照表。
#:
#: 来源：`外部调研_2026-09.md` §1.3。除标注 `E_PLATFORM` 的两条外，
#: 全部是媒体转述 —— **方向可信、细节存疑**，不得对外宣称「平台就是这么判的」。
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "emotion_gradient",
        "段落间情绪梯度",
        ("emotion_curve_match", "value_charge_flip"),
        E_REPORTED,
        "Keel 侧判的是「与声明弧线是否匹配」，与平台的判定口径**不完全相同**",
    ),
    Dimension(
        "foreshadow_cadence",
        "伏笔回收节奏",
        ("enigma_resolution", "thread_budget"),
        E_REPORTED,
    ),
    Dimension(
        "motivation_consistency",
        "角色动机一致性",
        ("lie_arc_closure", "belief_consistency"),
        E_REPORTED,
    ),
    Dimension(
        "emotion_anchor_drift",
        "情感锚点偏移率",
        ("dress",),
        E_REPORTED,
        "Keel 用 dress.py 的风格漂移近似；平台的「锚点」定义未公开",
    ),
    Dimension(
        "turning_point_position",
        "转折点固定在 1/3 或 2/3",
        ("template_coverage",),
        E_REPORTED,
    ),
    Dimension(
        "scene_length_uniform",
        "章节字数高度均等（±5%）",
        ("length_burstiness",),
        E_PLATFORM,
        "本轮新增，见 `rhythm.py`",
    ),
    Dimension(
        "adverb_density",
        "一段话 >4 次高频副词（极其/异常/不可思议）",
        ("adverb_density",),
        E_PLATFORM,
        "本轮新增，见 `rhythm.py`",
    ),
    Dimension(
        "dialogue_rhythm",
        "对话一问一答工整无打断",
        ("dialogue_rhythm",),
        E_PLATFORM,
        "本轮新增，见 `rhythm.py`",
    ),
    Dimension(
        "burstiness",
        "困惑度 / 爆发度（句长与段落长度分布）",
        ("length_burstiness",),
        E_REPORTED,
        "**困惑度本身 Keel 不计算**（需要语言模型）；爆发度用分布特征近似",
    ),
    Dimension(
        "watermark_syntax",
        "正文水印句式（「不是 X，是 Y」、破折号滥用）",
        ("anti_slop",),
        E_REPORTED,
        "`anti_slop` 覆盖「否定式煽情」，是其中的一类，不是全部",
    ),
    Dimension(
        "emotion_template",
        "情绪描写模板化（「眼眶通红、双拳紧握」）",
        ("anti_slop",),
        E_REPORTED,
    ),
    # -- Keel 结构上不做（不是「还没做」）--
    Dimension(
        "corpus_similarity",
        "与平台自有语料的相似度",
        (),
        E_REPORTED,
        "Keel 没有平台的语料，也**不应该有** —— 那是平台资产",
    ),
    Dimension(
        "perplexity",
        "困惑度（模型侧）",
        (),
        E_REPORTED,
        "需要语言模型推理；本项目承诺「无 API key 也能端到端跑通」，故不做",
    ),
    Dimension(
        "account_behavior",
        "账号行为特征（更新节奏、批量、IP）",
        (),
        E_REPORTED,
        "发生在发布环节，不在写作工具的能力范围内",
    ),
)

# ---------------------------------------------------------------------------
# 显式标识 / 隐式标识
# ---------------------------------------------------------------------------


def required_labels(ir: NarrativeIR) -> list[str]:
    """本作品**必须**出现在产物上的显式标识文案。

    Keel **提供文案，不能代为确认它真的被贴上去了** —— 那一步发生在
    渲染与发布环节。故自检报告里这些项的状态是「待人工确认」，不是「通过」。
    """
    if not any(s.origin is not ChunkOrigin.HUMAN for s in ir.scenes):
        return []
    out: list[str] = []
    if ir.medium is Medium.MICRO_DRAMA:
        # 广电总局令第 16 号 第 34 条
        out.append("每集明显位置：AI 生成")
    # 国信办通字〔2025〕2 号
    out.append("作品显著位置：本作品含 AI 生成合成内容")
    return out


def implicit_metadata(ir: NarrativeIR) -> dict:
    """隐式标识三要素（文件元数据须携带）。

    出处：《人工智能生成合成内容标识办法》要求生成合成内容的文件元数据中
    包含：**生成合成属性、服务提供者名称或编码、内容编号**。

    Keel 能做的是**生成这块元数据**；把它写进最终文件是渲染/导出环节的事。
    """
    models = sorted(
        {
            s.model_id
            for s in ir.scenes
            if s.model_id and s.origin is not ChunkOrigin.HUMAN
        }
    )
    involved = any(s.origin is not ChunkOrigin.HUMAN for s in ir.scenes)
    return {
        "生成合成属性": "AI 参与生成" if involved else "无 AI 参与",
        "服务提供者名称或编码": ", ".join(models) if models else "—",
        "内容编号": content_id(ir),
    }


def content_id(ir: NarrativeIR) -> str:
    """内容编号：**由内容派生**，同一份内容恒等。

    《标识办法》要求元数据里带内容编号，但没规定谁编。取内容哈希而不是
    时间戳或自增序号，理由是它让「同一份内容的两次导出编号一致」——
    申诉时需要证明「你交的就是这份」，一个会变的编号做不到这一点。
    """
    import hashlib

    digest = hashlib.sha1(ir.to_json().encode("utf-8")).hexdigest()
    return f"keel-{digest[:12]}"


# ---------------------------------------------------------------------------
# 自检项
# ---------------------------------------------------------------------------

#: 状态。与 severity 不同：这里记的是**结论性质**，不是扣分等级。
OK = "ok"
WARN = "warn"
BLOCKED = "blocked"
#: Keel 证明不了，必须作者自己确认。**这一态必须存在** ——
#: 把它并进 ok 就是在宣称「Keel 全查过了」。
MANUAL = "manual"


@dataclass
class CheckItem:
    layer: str  # A 法律义务 / B 平台画像 / C 不可检
    key: str
    status: str
    label: str
    detail: str
    basis: str = ""

    @property
    def glyph(self) -> str:
        return {OK: "✓", WARN: "!", BLOCKED: "✗", MANUAL: "?"}[self.status]


@dataclass
class SubmissionChecklist:
    title: str
    items: list[CheckItem] = field(default_factory=list)
    participation: ParticipationReport | None = None
    advisory: list[Finding] = field(default_factory=list)
    dimension_rows: list[tuple[Dimension, bool]] = field(default_factory=list)
    #: 由 `pre_submit_check` 填充（不放进调用签名，是为了让调用方只传 IR）
    required_label_texts: list[str] = field(default_factory=list)
    metadata_block: dict = field(default_factory=dict)

    # -- 汇总 --

    @property
    def blockers(self) -> list[CheckItem]:
        return [i for i in self.items if i.status == BLOCKED]

    @property
    def warnings(self) -> list[CheckItem]:
        return [i for i in self.items if i.status == WARN]

    @property
    def manual(self) -> list[CheckItem]:
        return [i for i in self.items if i.status == MANUAL]

    def verdict(self) -> tuple[str, str]:
        if self.blockers:
            return (
                "BLOCKED",
                f"{len(self.blockers)} 项硬阻塞：投稿前必须处理。",
            )
        if self.warnings:
            return (
                "CAUTION",
                f"{len(self.warnings)} 项需留意；"
                f"{len(self.manual)} 项须作者自行确认（Keel 证明不了）。",
            )
        return (
            "OK",
            f"Keel 可检的部分没有硬阻塞；仍有 {len(self.manual)} 项须作者确认。",
        )

    @property
    def dimension_coverage(self) -> tuple[int, int]:
        """（有对应能力的维度数, 维度总数）—— **派生**，不手写。"""
        covered = sum(1 for _d, ok in self.dimension_rows if ok)
        return covered, len(self.dimension_rows)

    def render(self) -> str:
        L = [f"── {self.title} " + "─" * max(0, 36 - len(self.title))]
        L.append("")
        L.append("  依据：")
        for name, cite, scope in REGULATIONS:
            L.append(f"    · {name}（{cite}）")
            L.append(f"      {scope}")
        L.append("")

        for layer, header in (
            ("A", "法律义务（Keel 可机检）"),
            ("B", "平台画像（统计画像，不是判决）"),
            ("C", "Keel 检不了 —— 须作者自行确认"),
        ):
            rows = [i for i in self.items if i.layer == layer]
            if not rows:
                continue
            L.append(f"── {layer}. {header} " + "─" * max(0, 30 - len(header)))
            for i in rows:
                L.append(f"  {i.glyph} {i.label}")
                L.append(f"      {i.detail}")
                if i.basis:
                    L.append(f"      依据：{i.basis}")
            L.append("")

        cov, total = self.dimension_coverage
        L.append("── 平台维度对照 " + "─" * 40)
        L.append(
            f"  Keel 有对应能力的维度 {cov}/{total}。"
            f"**这不等于「平台的判定覆盖了 {cov}/{total}」** —— "
        )
        L.append("  平台的完整维度未公开，且包含 Keel 结构上拿不到的信息。")
        for d, ok in self.dimension_rows:
            mark = "✓" if ok else "⊘"
            L.append(f"    {mark} {d.platform}")
            if d.note:
                L.append(f"        {d.note}")
            L.append(f"        证据等级：{d.evidence}")
        L.append("")

        if self.advisory:
            L.append(f"── 画像类提示（{len(self.advisory)} 项，不计入健康分）" + "─" * 12)
            for f in self.advisory:
                L.append(f.render())
            L.append("")

        level, note = self.verdict()
        L.append("─" * 56)
        L.append(f"  结论 [{level}] {note}")
        L.append(
            f"  阻塞 {len(self.blockers)} · 留意 {len(self.warnings)} "
            f"· 待人工确认 {len(self.manual)}"
        )
        L.append("")
        L.append("  ⚠ 本自检**不是**「不会被判 AI」的保证。它只报告 Keel")
        L.append("    在确定性维度上看到的东西；平台的判定用了 Keel 看不到的信息。")
        return "\n".join(L)

    def to_json(self) -> str:
        level, note = self.verdict()
        cov, total = self.dimension_coverage
        return json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "title": self.title,
                "level": level,
                "note": note,
                "counts": {
                    "blocked": len(self.blockers),
                    "warn": len(self.warnings),
                    "manual": len(self.manual),
                },
                "dimension_coverage": {"covered": cov, "total": total},
                "items": [
                    {
                        "layer": i.layer,
                        "key": i.key,
                        "status": i.status,
                        "label": i.label,
                        "detail": i.detail,
                        "basis": i.basis,
                    }
                    for i in self.items
                ],
                "advisory": [
                    {"code": f.code, "message": f.message, "scene_id": f.scene_id}
                    for f in self.advisory
                ],
                "required_labels": self.required_label_texts,
                "implicit_metadata": self.metadata_block,
                "participation": (
                    {
                        "ai_ratio": round(self.participation.ai_ratio, 4),
                        "trace_coverage": round(self.participation.trace_coverage, 4),
                        "level": self.participation.verdict()[0],
                    }
                    if self.participation
                    else None
                ),
                "regulations": [
                    {"name": n, "cite": c, "scope": s} for n, c, s in REGULATIONS
                ],
            },
            ensure_ascii=False,
            indent=2,
        )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def pre_submit_check(ir: NarrativeIR, report: Report | None = None) -> SubmissionChecklist:
    """跑一次投稿前自检。

    `report` 可传入已算好的体检报告（省一次全量校验）；不传则现算。
    """
    _refresh_registry()
    rep = report if report is not None else run_all(ir)

    # -- 溯源与 AI 占比 --
    ledger = ProvenanceLedger()
    if ir.provenance:
        ledger.records = list(ir.provenance)
    else:
        for s in ir.scenes:
            ledger.record(
                chunk_id=f"chunk_{s.id}",
                scene_id=s.id,
                origin=s.origin,
                model_id=s.model_id,
                prompt_version=s.prompt_version,
                human_edit_ratio=0.0,
                char_count=len(s.prose or ""),
            )
    part = ledger.report(ir)

    items: list[CheckItem] = []

    # -- A. 法律义务 --
    level, note = part.verdict()
    items.append(
        CheckItem(
            "A",
            "ai_ratio",
            BLOCKED if level == "BLOCKED" else (WARN if level == "CAUTION" else OK),
            f"AI 占比 {part.ai_ratio:.2%}",
            note,
            "起点/番茄 2026 年 7–8 月口径：AI 内容占比 >10% 即处理",
        )
    )

    if part.trace_coverage < 1.0:
        items.append(
            CheckItem(
                "A",
                "trace_coverage",
                BLOCKED if part.ai_ratio > 0 else WARN,
                f"溯源覆盖 {part.trace_coverage:.0%}（{part.traced_scenes}/{part.scene_count}）",
                "有场景没有溯源记录 —— 占比数字**不可证明**。"
                + ("且 AI 占比 >0，无法证明的部分会被按最坏情况对待。" if part.ai_ratio > 0 else ""),
                "《标识办法》要求标识义务可追溯；申诉时台账是唯一证据",
            )
        )
    else:
        items.append(
            CheckItem(
                "A",
                "trace_coverage",
                OK,
                "溯源覆盖 100%",
                "每一个场景都有溯源记录，占比数字可证明。",
                "",
            )
        )

    labels = required_labels(ir)
    if labels:
        items.append(
            CheckItem(
                "A",
                "explicit_label",
                MANUAL,
                "显式标识（待作者确认）",
                "必须出现在产物上："
                + "；".join(labels)
                + "。Keel 只提供文案 —— **贴没贴上去它看不到**。",
                "；".join(f"{n}（{c}）" for n, c, _ in REGULATIONS),
            )
        )
        items.append(
            CheckItem(
                "A",
                "implicit_label",
                MANUAL,
                "隐式标识（文件元数据，待作者确认）",
                "导出文件时须写入元数据："
                + "、".join(f"{k}={v}" for k, v in implicit_metadata(ir).items()),
                "《人工智能生成合成内容标识办法》（国信办通字〔2025〕2 号）",
            )
        )
    else:
        items.append(
            CheckItem(
                "A",
                "explicit_label",
                OK,
                "无需标识",
                "全部场景均为人工原创（溯源层面无 AI 参与）。",
                "",
            )
        )

    # -- B. 平台画像（advisory，不进健康分）--
    rhythm = scan_rhythm_ir(ir)
    if rhythm:
        items.append(
            CheckItem(
                "B",
                "rhythm",
                WARN,
                f"{len(rhythm)} 项文本画像命中",
                "；".join(f.message.split("：")[0] for f in rhythm)
                + "。这些是**统计画像**，不是判决 —— 人类作者同样会命中。",
                "番茄公开口径（章节 ±5%、一段 >4 次高频副词、对话工整无打断）",
            )
        )

    # -- C. Keel 检不了 --
    for d in DIMENSIONS:
        if d.keel:
            continue
        items.append(
            CheckItem(
                "C",
                d.key,
                MANUAL,
                f"{d.platform}（Keel 不做）",
                d.note or "不在 Keel 的能力范围内。",
                f"证据等级：{d.evidence}",
            )
        )
    items.append(
        CheckItem(
            "C",
            "platform_discretion",
            MANUAL,
            "平台的最终判定（Keel 无法预知）",
            "平台保留编辑复核、读者举报、动态复审与未公开维度。"
            "**没有任何工具能承诺通过率**，承诺了就是在骗人。",
            "",
        )
    )

    rows = [(d, d.covered) for d in DIMENSIONS]
    return SubmissionChecklist(
        title=f"{ir.title} · 投稿前合规自检",
        items=items,
        participation=part,
        advisory=rhythm,
        dimension_rows=rows,
        required_label_texts=labels,
        metadata_block=implicit_metadata(ir),
    )
