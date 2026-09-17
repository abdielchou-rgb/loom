"""反 slop 检测。

「AI 味」不是玄学，是可以量化的一组模式。这些模式来自中文写作社区
（起点撤榜事件、番茄「空洞水文」拒签）与英文社区（"gray goo prose"）
反复指认的具体形态：

    否定式煽情    「这不仅是 X，而是 Y」
    虚假范围      「从 X 到 Y」
    最高级堆叠    「最」「极致」「前所未有」
    过度对偶排比  整齐得不像人写的三连句
    情绪直述      「他感到无比愤怒」而不是呈现愤怒
    总结式收尾    每段结尾都升华一次
    比喻密度过载  一句话三个比喻
    同质化        重复句式模板

注意：这些规则会产生误报（人类作者也会用），因此全部输出为 WARN/INFO，
不阻断生成，只作为体检项。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from ..ir.enums import Severity
from ..validators.base import Finding

# --- 中文 AI 味模式 ---

_NEGATION_HYPE = [
    r"这不仅仅?是.{1,20}而是",
    r"这不仅是.{1,20}更是",
    r"与其说是.{1,20}不如说",
    r"不是.{1,15}而是.{1,15}——",
]

_FALSE_RANGE = [
    r"从.{1,12}到.{1,12}，",
    r"无论是.{1,12}还是.{1,12}",
]

_SUPERLATIVE_STACK = [
    r"前所未有",
    r"无与伦比",
    r"前所未见",
    r"极致的?[^。，]{0,6}",
    r"堪称.{0,6}典范",
]

_EMOTION_TELLING = [
    r"他感到[无十]?比?[^。，]{0,6}(愤怒|悲伤|绝望|痛苦|喜悦|震惊)",
    r"她感到[无十]?比?[^。，]{0,6}(愤怒|悲伤|绝望|痛苦|喜悦|震惊)",
    r"心中涌起[一]?股?[^。，]{0,6}(情绪|暖流|悲伤|愤怒)",
    r"泪水[^。，]{0,4}(夺眶而出|模糊了双眼)",
    r"心头一[颤紧震]",
]

_SUMMARY_ENDING = [
    r"这一刻，[^。]{0,30}。$",
    r"他终于明白了[^。]{0,30}。$",
    r"命运的?齿轮[^。]{0,20}",
    r"一切[都终]将[^。]{0,20}。$",
]

_CLICHE = [
    r"空气仿佛凝固",
    r"时间仿佛静止",
    r"死一般的寂静",
    r"眼神中闪过一丝[^。，]{0,4}",
    r"嘴角勾起一抹[^。，]{0,6}",
    r"不由自主地",
    r"鬼使神差",
]

_ENGLISH_SLOP = [
    r"\ba testament to\b",
    r"\bdelve[sd]? into\b",
    r"\bit'?s not just .{1,30}, it'?s\b",
    r"\btapestry of\b",
    r"\bin the realm of\b",
    r"\bnavigate the complexities\b",
    r"\bleaves? an indelible mark\b",
]

_ALL_PATTERNS: list[tuple[str, list[str]]] = [
    ("negation_hype", _NEGATION_HYPE),
    ("false_range", _FALSE_RANGE),
    ("superlative_stack", _SUPERLATIVE_STACK),
    ("emotion_telling", _EMOTION_TELLING),
    ("summary_ending", _SUMMARY_ENDING),
    ("cliche", _CLICHE),
    ("english_slop", _ENGLISH_SLOP),
]

_COMPILED: list[tuple[str, list[re.Pattern[str]]]] = [
    (name, [re.compile(p, re.MULTILINE | re.IGNORECASE) for p in pats])
    for name, pats in _ALL_PATTERNS
]


@dataclass
class SlopHit:
    kind: str
    pattern: str
    sample: str
    count: int


@dataclass
class SlopReport:
    scene_id: str | None
    char_count: int
    hits: list[SlopHit]
    metaphor_density: float
    sentence_len_cv: float
    repetition_ratio: float

    @property
    def score(self) -> int:
        """0-100 的「去 AI 味」得分，越高越像人写的。"""
        penalty = 0.0
        weights = {
            "negation_hype": 9,
            "false_range": 7,
            "superlative_stack": 6,
            "emotion_telling": 5,
            "summary_ending": 4,
            "cliche": 6,
            "english_slop": 8,
        }
        for h in self.hits:
            penalty += weights.get(h.kind, 4) * min(h.count, 3)
        penalty += max(0.0, (self.metaphor_density - 0.6) * 40)
        penalty += max(0.0, (0.35 - self.sentence_len_cv) * 60)
        penalty += max(0.0, (self.repetition_ratio - 0.12) * 200)
        return max(0, min(100, int(100 - penalty)))


_METAPHOR_MARKERS = ["像", "仿佛", "如同", "好似", "宛如", "似的", "犹如"]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def scan_slop(text: str, scene_id: str | None = None) -> SlopReport:
    """扫描一段文本，返回 slop 报告。"""
    if not text.strip():
        return SlopReport(scene_id, 0, [], 0.0, 1.0, 0.0)

    hits: list[SlopHit] = []
    for kind, pats in _COMPILED:
        for p in pats:
            found = p.findall(text)
            if found:
                hits.append(
                    SlopHit(
                        kind=kind,
                        pattern=p.pattern,
                        sample=found[0] if isinstance(found[0], str) else str(found[0]),
                        count=len(found),
                    )
                )

    sentences = _split_sentences(text)
    n_sent = max(1, len(sentences))

    metaphor_count = sum(text.count(m) for m in _METAPHOR_MARKERS)
    metaphor_density = metaphor_count / n_sent

    lens = [len(s) for s in sentences] or [1]
    mean = sum(lens) / len(lens)
    var = sum((l - mean) ** 2 for l in lens) / len(lens)
    cv = (var**0.5) / mean if mean else 1.0

    # 句式重复：句子前 6 字的重复率
    heads = [s[:6] for s in sentences if len(s) >= 6]
    rep = 0.0
    if heads:
        c = Counter(heads)
        rep = sum(v for v in c.values() if v > 1) / len(heads)

    return SlopReport(
        scene_id=scene_id,
        char_count=len(text),
        hits=hits,
        metaphor_density=round(metaphor_density, 3),
        sentence_len_cv=round(cv, 3),
        repetition_ratio=round(rep, 3),
    )


_KIND_LABEL = {
    "negation_hype": "否定式煽情（这不仅是X而是Y）",
    "false_range": "虚假范围（从X到Y）",
    "superlative_stack": "最高级堆叠",
    "emotion_telling": "情绪直述（应呈现而非告知）",
    "summary_ending": "总结式升华收尾",
    "cliche": "陈词滥调",
    "english_slop": "英文 AI 套话",
}


def slop_findings(report: SlopReport) -> list[Finding]:
    """把 slop 报告转成体检项。"""
    out: list[Finding] = []
    sid = report.scene_id
    for h in report.hits:
        sev = Severity.WARN if h.count >= 2 else Severity.INFO
        out.append(
            Finding(
                code=f"slop:{h.kind}",
                severity=sev,
                scene_id=sid,
                message=f"{_KIND_LABEL.get(h.kind, h.kind)} ×{h.count}（例：{h.sample!r}）",
                suggestion="改写为具体呈现，或直接删除该句",
            )
        )
    if report.metaphor_density > 0.6:
        out.append(
            Finding(
                code="slop:metaphor_density",
                severity=Severity.WARN,
                scene_id=sid,
                message=f"比喻密度 {report.metaphor_density:.2f}/句，过载",
                suggestion="砍掉一半比喻；密集比喻是最典型的 AI 味来源",
            )
        )
    if report.sentence_len_cv < 0.35:
        out.append(
            Finding(
                code="slop:rhythm",
                severity=Severity.INFO,
                scene_id=sid,
                message=f"句长变异系数仅 {report.sentence_len_cv:.2f}，节奏过于均匀",
                suggestion="插入短句与长句，制造节奏起伏",
            )
        )
    if report.repetition_ratio > 0.12:
        out.append(
            Finding(
                code="slop:repetition",
                severity=Severity.WARN,
                scene_id=sid,
                message=f"句首重复率 {report.repetition_ratio:.0%}，句式模板化",
                suggestion="变换句式开头",
            )
        )
    return out


def scan_ir(ir) -> list[Finding]:
    """扫描整个 IR 的所有已写场景。"""
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.prose:
            continue
        rep = scan_slop(s.prose, scene_id=s.id)
        out.extend(slop_findings(rep))
        if rep.score < 60:
            out.append(
                Finding(
                    code="slop:score",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message=f"去 AI 味得分偏低：{rep.score}/100",
                    suggestion="优先重写被标记的句子",
                )
            )
    return out
