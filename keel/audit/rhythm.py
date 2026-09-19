"""三个**平台合规向**的确定性检测器 —— 爆发度 / 副词密度 / 对话节奏。

与 `anti_slop.py` / `craft.py` 的分工
────────────────────────────────────

那两个模块回答的是「**这段文字好不好**」（AI 味、张力、控制感、现实效应）。
本模块回答的是另一个问题：「**这段文字在平台检测器眼里像不像机器写的**」。

区别不是措辞，是**判据来源不同**：

  * `anti_slop` / `craft` 的判据来自**文学方法论**（Maass / Barthes / Storr）；
  * 本模块的判据来自**平台公开的风控口径** —— 平台不会因为一段文字
    「张力密度低」就限流，但会因为「章节字数高度均等」把稿子标为 AI 可疑。

两者会重叠（句长均匀既是不好读，也是 AI 特征），但**重叠不是重复**：
同一段文字可能被 `slop:rhythm` 报「节奏单调」，同时被本模块报
「落到平台的均匀区间」。前者建议改写，后者提示投稿风险。

── 三份出处（可复核，不发明）────────────────────────────────

  1. **爆发度（burstiness）** —— Goh & Barabási,
     *Burstiness and memory in complex systems*, EPL 81, 48002 (2008)：

         B = (σ − μ) / (σ + μ)

     区间 [−1, 1]。泊松过程 B = 0；完全均匀（等长）B = −1；
     重尾爆发 B → 1。这是**有名字、有出处**的统计量，不是「我觉得方差小」。

     平台侧的依据：番茄小说把「章节字数高度均等（±5%）」直接列为 AI 可疑
     信号；行业口径把「爆发度」与「困惑度」并列为两大 AI 检测指标。
     故本模块在**两个尺度**上算它：句长（微观节奏）与场长（宏观分章）。

  2. **高频副词密度** —— 番茄小说公开的风控口径：
     「一段话中出现超过 4 次『极其 / 异常 / 不可思议』等高频副词 → AI 可疑」。
      阈值是**平台的数字**，不是我们调出来的；本模块照抄它的口径
     （见常量 `_ADVERB_PARAGRAPH_LIMIT`，判据是「命中**超过**阈值」，
     与「超过 4 次」同义），以便作者看到的结论与平台口径一致。

  3. **对话节奏** —— 同上的第二条公开口径：
     「人物对话一问一答工整无打断 → 对话模式异常」。
     实现为：连续若干轮对话之间**没有任何叙述间隔**，且全篇**没有打断标记**。

── 严重度政策：一律 INFO，且走 advisory 通道 ─────────────────

三个检测器**只产出 INFO**，并且注册在 `validators/base.py` 的 `ADVISORY`
名单里 —— 它们的 Finding 进 `Report.advisory`，**不进健康分**。

两条理由，都不是口味问题：

  1. **它们不是结构缺陷。** `score()` 的名字是「结构健康分」。把「平台的
     统计画像与你的文本吻合」算成结构缺陷，会让头条指标无法解释：
     装一个新的检测器，分数就无声地往下掉，读者分不清是「故事变差了」
     还是「多装了一个检查」。（这条语义混杂是**已知的产品待决问题**，
     见 `craft.py` 末尾；本模块选择不加剧它，而不是假装解决它。）
  2. **假阳性的代价不对称。** 人类作者也写等长段落、也用「极其」。
     若本模块能产生 WARN，作者会为了一个统计画像去改写本来没问题的文字 ——
     而那正是「为检测器写作」，比 AI 味本身更糟。

── 红线：不提供反检测 ─────────────────────────────────────

**本模块的用途是「告诉作者平台会怎么看」，不是「帮作者骗过平台」。**
产品层面明确不做（见 `docs` 与 `README` 的红线条款）：

  * 不提供「降 AI 率」的一键改写；
  * 不提供按平台阈值反向优化的「洗稿」建议；
  * 阈值与词表**公开在源码里**，不做隐藏 —— 一个靠藏着阈值才能工作的
    检测器，道德上站不住，技术上也会在平台换口径的当天失效。

理由三条：技术上打不赢（检测器与生成器的军备竞赛中，公开的一方永远
滞后一步）；道德上站不住（规避标识义务）；商业上致命（一旦被认定为
提供规避工具，连带责任远大于功能收益）。

── 已知局限（写出来，不藏着）────────────────────────────

  * **爆发度是分布特征，不是判决。** B 高不等于写得好，B 低不等于 AI 写的。
    它筛的是「值得作者自己再看一眼」，不是「这是 AI」。
  * **句长爆发度在短文本上不稳。** 少于 `_BURST_MIN_SENTENCES` 句时
    CV 本身噪声很大，故直接不判（这个下限是必要的：拿 3 句话算方差，
    得到的数字只反映这 3 句话，不反映作者）。
  * **副词表是中文 LLM 的高频腔，不是全部副词。** 表里每条都能在
    LLM 生成中文里高频复现；人类写作里同样常见（尤其网络文学）。
    所以判据是**密度**而不是**出现** —— 一段里 1 个「极其」不是问题，
    5 个才是。
  * **对话检测只认引号。** 「」『』“"” 四种；破折号引导的对话
    （「——你来了。」）与无引号的对白抓不到。中文网络文学大量使用
    无引号对话，这部分是盲区。
  * **「无打断」只看标记词。** 真正的打断也可以写成动作（「她抬手止住他」），
    本模块认不出。故 `interruption_count` 为 0 只说明**没有打断标记**，
    不说明**没有被打断** —— 文案里必须说清这一点，不能让作者读成
    「你写了完美的对话」。
  * **切句/切段是第四份同义实现**（另有 `anti_slop._split_sentences`、
    `craft._sentences`、`transportation._sentences`）。此处不统一：
    前三份各自被成体系的测试钉死，合并的收益（少三份六行代码）
    小于改动风险。记录为已知重复。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ir.enums import Severity
from ..validators.base import Finding

# ---------------------------------------------------------------------------
# 共用：切分
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")

#: 引号对。顺序不可换：左半边在前，右半边在后。
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ("「", "」"),
    ("『", "』"),
    ("“", "”"),
    ('"', '"'),
)

_QUOTE_SPAN = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\"")


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]


def _paragraphs(text: str) -> list[str]:
    """中文网文一行即一段，故按换行切。"""
    return [p.strip() for p in re.split(r"\n+", text) if p.strip()]


def _cv(values: list[float]) -> float:
    """变异系数 σ/μ。空表或均值为 0 时返回 0.0（无可判的离散度）。"""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return var**0.5 / mean


def burstiness(values: list[float]) -> float:
    """Goh & Barabási (2008) 的爆发度系数 B = (σ − μ) / (σ + μ)。

        B = −1  完全均匀（等长）
        B =  0  泊松（无记忆随机）
        B → 1  重尾爆发

    这是**有出处**的统计量，不是自造的「方差小」。
    """
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    sd = var**0.5
    return (sd - mean) / (sd + mean)


# ===========================================================================
# 1. 爆发度 —— 句长（微观）与场长（宏观）
# ===========================================================================

#: 句长爆发度低于此值 → 报。B = −0.5 对应 CV = 1/3，
#: 与 `anti_slop` 里「CV < 0.35 报节奏单调」的经验阈值**同量级** ——
#: 两份独立来源落到同一个区间，是它可信的一点证据。
_BURST_SENTENCE_MIN = -0.5
#: 句子数下限。少于它 CV 本身噪声过大，不判。
_BURST_MIN_SENTENCES = 8
#: 场长判定所需的最少「有正文的场次」数。两场比不出分布。
_BURST_MIN_SCENES = 3
#: 场长最大相对偏离。0.05 = 番茄公开的「章节字数高度均等（±5%）」口径。
_SCENE_DEVIATION_MAX = 0.05


@dataclass
class BurstinessReport:
    """一份稿子（跨场）的长度分布画像。

    **为什么是全局的**：`anti_slop` 的 `slop:rhythm` 逐场算句长 CV，
    而平台的「章节字数均等」判的是**整本书的章节分布** —— 一个逐场
    检测器在结构上就看不到它。故本模块的句长尺度也是跨场汇总的：
    单场 CV 高不代表整本的分布不均匀。
    """

    scene_count: int
    sentence_count: int
    sentence_burstiness: float
    sentence_cv: float
    scene_lengths: list[int] = field(default_factory=list)
    scene_burstiness: float = 0.0
    scene_cv: float = 0.0
    #: 最长的场相对均值的偏离（|len − mean| / mean 的最大值）。
    scene_max_deviation: float = 0.0

    @property
    def uniform_sentences(self) -> bool:
        return (
            self.sentence_count >= _BURST_MIN_SENTENCES
            and self.sentence_burstiness < _BURST_SENTENCE_MIN
        )

    @property
    def uniform_scenes(self) -> bool:
        """全部场次都落在均值的 ±5% 内 —— 番茄的公开口径。"""
        return (
            len(self.scene_lengths) >= _BURST_MIN_SCENES
            and self.scene_max_deviation <= _SCENE_DEVIATION_MAX
        )


def scan_burstiness(prose_by_scene: list[str]) -> BurstinessReport:
    """跨场统计句长与场长的分布。

    入参是**各场正文的列表**（按话语顺序），不是整段拼好的文本 ——
    场长是本检测器的一个维度，拼起来就丢了。
    """
    texts = [t for t in prose_by_scene if t and t.strip()]
    lengths = [len(t) for t in texts]
    sentences = [len(s) for t in texts for s in _sentences(t)]

    if not texts:
        return BurstinessReport(0, 0, 0.0, 0.0, [], 0.0, 0.0, 0.0)

    mean_scene = sum(lengths) / len(lengths)
    max_dev = (
        max(abs(n - mean_scene) for n in lengths) / mean_scene if mean_scene else 0.0
    )
    return BurstinessReport(
        scene_count=len(texts),
        sentence_count=len(sentences),
        sentence_burstiness=round(burstiness([float(n) for n in sentences]), 3),
        sentence_cv=round(_cv([float(n) for n in sentences]), 3),
        scene_lengths=lengths,
        scene_burstiness=round(burstiness([float(n) for n in lengths]), 3),
        scene_cv=round(_cv([float(n) for n in lengths]), 3),
        scene_max_deviation=round(max_dev, 3),
    )


def burstiness_findings(report: BurstinessReport) -> list[Finding]:
    """把分布画像转成体检项。**两条都可能是零** —— 分布正常就该不报。"""
    out: list[Finding] = []
    if report.uniform_sentences:
        out.append(
            Finding(
                code="length_burstiness",
                severity=Severity.INFO,
                message=(
                    f"句长爆发度 B={report.sentence_burstiness:.2f}"
                    f"（CV {report.sentence_cv:.2f}，{report.sentence_count} 句）："
                    "全长句分布过于均匀，落在平台的「机器节奏」区间"
                ),
                suggestion=(
                    "不是要你随机化句长 —— 是在信息密度高的地方用短句（动作、"
                    "转折、对白），在铺陈处用长句。均匀不是毛病，**没有意图的均匀**才是"
                ),
                evidence={
                    "axis": "sentence",
                    "burstiness": report.sentence_burstiness,
                    "cv": report.sentence_cv,
                    "sentence_count": report.sentence_count,
                    "threshold": _BURST_SENTENCE_MIN,
                },
            )
        )
    if report.uniform_scenes:
        out.append(
            Finding(
                code="length_burstiness",
                severity=Severity.INFO,
                message=(
                    f"{len(report.scene_lengths)} 个场次的字数全部落在均值的 ±5% 内"
                    f"（最大偏离 {report.scene_max_deviation:.1%}，"
                    f"爆发度 B={report.scene_burstiness:.2f}）："
                    "平台把「章节字数高度均等」直接列为 AI 可疑信号"
                ),
                suggestion=(
                    "按**叙事需要**分章，不按字数分章：把高潮场单独切开，"
                    "把过渡场合并。分章长度应当跟着节拍走，而不是跟着配额走"
                ),
                evidence={
                    "axis": "scene",
                    "burstiness": report.scene_burstiness,
                    "max_deviation": report.scene_max_deviation,
                    "scene_lengths": report.scene_lengths,
                    "threshold": _SCENE_DEVIATION_MAX,
                },
            )
        )
    return out


# ===========================================================================
# 2. 高频副词密度
# ===========================================================================

#: 中文 LLM 生成文本里的高频腔。逐类推导，不抄任何第三方词表：
#:
#:   程度强化  「极其 / 异常 / 无比」——模型不会说「很好」，它会说「极其好」；
#:             强度靠副词叠，而不是靠选更准的动词。
#:   突转      猛地 / 忽然 / 霎时 ——模型偏爱显式的时间标记来制造戏剧性，
#:             人类更常直接写动作。
#:   情态      下意识 / 不由得 / 情不自禁 ——模型用它代替对人物动机的具体化。
#:   评价      不可思议 / 难以置信 ——模型**替读者下结论**，而不是让人物
#:             自己去反应。
#:   轻量化    微微 / 一丝 / 淡淡 ——模型的「克制」也是模板化的克制。
_ADVERB_GROUPS: dict[str, tuple[str, ...]] = {
    "程度强化": (
        "极其", "异常", "非常", "十分", "格外", "无比", "尤为", "极度",
        "过于", "太过", "分外", "何等", "相当", "特别", "尤为",
    ),
    "突转": ("猛地", "忽然", "骤然", "霎时", "瞬间", "一瞬间", "刹那", "顿时"),
    "情态": ("下意识", "不由得", "情不自禁", "忍不住", "莫名", "不由自主"),
    "评价": ("不可思议", "难以置信", "匪夷所思", "出奇"),
    "轻量化": ("微微", "稍稍", "略略", "些许", "一丝", "一抹", "几分", "淡淡"),
}

_ADVERB_WORDS: dict[str, str] = {
    w: cat for cat, ws in _ADVERB_GROUPS.items() for w in ws
}
_ADVERB_RE = re.compile(
    "|".join(sorted(_ADVERB_WORDS, key=len, reverse=True))
)

#: 一段内命中**超过**这个数 → 报。4 是番茄公开的口径（「超过 4 次」）。
_ADVERB_PARAGRAPH_LIMIT = 4


@dataclass
class AdverbParagraph:
    index: int
    char_count: int
    hits: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.hits)

    @property
    def flagged(self) -> bool:
        return self.count > _ADVERB_PARAGRAPH_LIMIT


@dataclass
class AdverbReport:
    scene_id: str | None
    char_count: int
    paragraphs: list[AdverbParagraph] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(p.count for p in self.paragraphs)

    @property
    def density(self) -> float:
        """每百字命中数。"""
        return self.total * 100 / self.char_count if self.char_count else 0.0

    @property
    def flagged(self) -> list[AdverbParagraph]:
        return [p for p in self.paragraphs if p.flagged]


def scan_adverbs(text: str, scene_id: str | None = None) -> AdverbReport:
    """逐段统计高频副词。判据是**密度**，不是**出现**。"""
    if not text.strip():
        return AdverbReport(scene_id, 0, [])
    return AdverbReport(
        scene_id=scene_id,
        char_count=len(text),
        paragraphs=[
            AdverbParagraph(
                index=i,
                char_count=len(para),
                hits=_ADVERB_RE.findall(para),
            )
            for i, para in enumerate(_paragraphs(text))
        ],
    )


def adverb_findings(report: AdverbReport) -> list[Finding]:
    """只报**超过阈值**的段落，并点名命中最多的是哪一类。"""
    out: list[Finding] = []
    for p in report.flagged:
        cats: dict[str, int] = {}
        for w in p.hits:
            cats[_ADVERB_WORDS[w]] = cats.get(_ADVERB_WORDS[w], 0) + 1
        top = max(cats.items(), key=lambda kv: kv[1])[0]
        out.append(
            Finding(
                code="adverb_density",
                severity=Severity.INFO,
                scene_id=report.scene_id,
                message=(
                    f"第{p.index + 1}段高频副词 {p.count} 次"
                    f"（>{_ADVERB_PARAGRAPH_LIMIT}，以「{top}」类为主："
                    f"{'、'.join(p.hits[:5])}）："
                    "平台把「一段超过 4 次高频副词」列为 AI 可疑信号"
                ),
                suggestion=(
                    "删掉副词，把强度交给动词：不是「极其愤怒地摔门」，"
                    "而是「摔门」。副词是强度的**补丁**，补丁够多说明动词选错了"
                ),
                evidence={
                    "paragraph": p.index,
                    "count": p.count,
                    "by_category": cats,
                    "samples": p.hits[:8],
                    "threshold": _ADVERB_PARAGRAPH_LIMIT,
                },
            )
        )
    return out


# ===========================================================================
# 3. 对话节奏 —— 一问一答工整无打断
# ===========================================================================

#: 打断标记。**只认标记词**，不认「抬手止住他」这类写成动作的打断 ——
#: 这是已知盲区，故文案里说的是「无打断标记」，不是「无打断」。
#:
#: 「沉默」**不收裸词**，只收「沉默了 / 一阵沉默 / 陷入沉默」这类**
#: 带谓语或量词的短语**。理由是一次实测碰撞：样例里的「无比沉默」
#: （副词 + 形容词，描述状态）被当成一次打断，于是那段工整对白被判成
#: 「有打断」而漏报。裸「沉默」在中文里既可能是停顿标记，也可能只是
#: 一个形容词谓语 —— 子串匹配分不开，加语境约束（后面接「了」或前面
#: 有量词）就能分开绝大部分。**这是子串匹配的固有代价，不是待修的 bug。**
_INTERRUPTIONS: tuple[str, ...] = (
    "打断", "插嘴", "插话", "抢话", "抢过话", "欲言又止", "顿了顿",
    "停了停", "沉默了", "一阵沉默", "陷入沉默", "沉默片刻", "半晌",
    "没说完", "话没说完", "欲言", "迟疑",
    "支吾", "结巴", "咽了回去", "把话咽", "话到嘴边", "被打断",
)

_INTERRUPTION_RE = re.compile("|".join(sorted(_INTERRUPTIONS, key=len, reverse=True)))

_QUESTION_MARKS = ("？", "?")

#: 「工整」的判据：连续这么多轮对话之间**没有任何叙述间隔**。
#: 4 轮 = 两问两答。少于它，两三轮紧凑对白是正常的，甚至是好的。
_BARE_RUN_MIN = 4


@dataclass
class DialogueRhythmReport:
    """一场对话的节奏画像。"""

    scene_id: str | None
    turn_count: int = 0
    #: 最长的「无叙述间隔」连续对话轮数。
    bare_run: int = 0
    #: 连续「问 → 答」的对数（在最长裸跑内数）。
    qa_pairs: int = 0
    interruption_count: int = 0
    mean_turn_len: float = 0.0

    @property
    def has_dialogue(self) -> bool:
        return self.turn_count > 0

    @property
    def monotonic(self) -> bool:
        """工整无打断：连续 ≥N 轮无叙述间隔 **且** 全篇没有打断标记。

        两个条件缺一不可：有打断标记却仍然连续裸跑，恰恰说明作者**写了**
        打断（比如「她打断他」之后紧接着又是一串纯对白），那种不是模板。
        """
        return self.bare_run >= _BARE_RUN_MIN and self.interruption_count == 0


def _turns(text: str) -> list[str]:
    return [m.group(0) for m in _QUOTE_SPAN.finditer(text)]


def _max_bare_run(text: str, turns: list[str]) -> tuple[int, int]:
    """最长「无叙述间隔」连续对话轮数，以及其中的「问→答」对数。

    做法：按引号区间把文本切开，看相邻两轮之间的**间隙**有没有实质内容。
    间隙里只剩标点/空白 → 这两轮是「背靠背」的（没有叙述、没有动作、
    没有反应描写）—— 正是一问一答工整无打断的形态。
    """
    if not turns:
        return 0, 0

    gaps: list[str] = []
    cursor = 0
    for m in _QUOTE_SPAN.finditer(text):
        gaps.append(text[cursor : m.start()])
        cursor = m.end()
    # gaps[0] 是第一轮之前的内容，与「两轮之间」无关，丢弃
    between = gaps[1:] if len(gaps) > 1 else []
    between += [""]  # 最后一轮之后没有间隔，视作裸跑的收尾

    best_run, best_qa = 0, 0
    run, qa = 1, 0
    prev_was_question = any(q in turns[0] for q in _QUESTION_MARKS)
    for i, gap in enumerate(between):
        if i >= len(turns) - 1:
            break
        bare = not re.sub(r"[\s，,、。．:：；;！!？?~—\-…]+", "", gap)
        if bare:
            run += 1
            cur_is_question = any(q in turns[i + 1] for q in _QUESTION_MARKS)
            if prev_was_question and not cur_is_question:
                qa += 1
            prev_was_question = cur_is_question
        else:
            if run > best_run:
                best_run, best_qa = run, qa
            run, prev_was_question = 1, any(
                q in turns[i + 1] for q in _QUESTION_MARKS
            )
            qa = 0
    if run > best_run:
        best_run, best_qa = run, qa
    return best_run, best_qa


def scan_dialogue_rhythm(text: str, scene_id: str | None = None) -> DialogueRhythmReport:
    """统计对话轮次、最长裸跑、打断标记。"""
    if not text.strip():
        return DialogueRhythmReport(scene_id)

    turns = _turns(text)
    if not turns:
        return DialogueRhythmReport(scene_id)

    bare_run, qa = _max_bare_run(text, turns)
    return DialogueRhythmReport(
        scene_id=scene_id,
        turn_count=len(turns),
        bare_run=bare_run,
        qa_pairs=qa,
        interruption_count=len(_INTERRUPTION_RE.findall(text)),
        mean_turn_len=round(sum(len(t) for t in turns) / len(turns), 1),
    )


def dialogue_rhythm_findings(report: DialogueRhythmReport) -> list[Finding]:
    out: list[Finding] = []
    if not report.monotonic:
        return out
    out.append(
        Finding(
            code="dialogue_rhythm",
            severity=Severity.INFO,
            scene_id=report.scene_id,
            message=(
                f"连续 {report.bare_run} 轮对话之间没有叙述间隔"
                f"（其中 {report.qa_pairs} 组问→答），且全篇无打断标记："
                "平台把「一问一答工整无打断」列为对话模式异常"
            ),
            suggestion=(
                "在两轮对白之间插一点**非对白**：说话人的动作、听话人的反应、"
                "一句没说出口的话。真实对话是被不断打断的，工整是对话的敌人"
            ),
            evidence={
                "turn_count": report.turn_count,
                "bare_run": report.bare_run,
                "qa_pairs": report.qa_pairs,
                "interruption_count": report.interruption_count,
                "mean_turn_len": report.mean_turn_len,
                "threshold": _BARE_RUN_MIN,
            },
        )
    )
    return out


# ===========================================================================
# 顶层：三个一起跑
# ===========================================================================


def scan_ir(ir) -> list[Finding]:
    """扫描整个 IR。爆发度是跨场的，故单独取一次各场正文。"""
    scenes = [s for s in ir.ordered_scenes() if s.prose]
    if not scenes:
        return []

    out: list[Finding] = []
    out.extend(burstiness_findings(scan_burstiness([s.prose for s in scenes])))
    for s in scenes:
        out.extend(adverb_findings(scan_adverbs(s.prose, scene_id=s.id)))
        out.extend(
            dialogue_rhythm_findings(scan_dialogue_rhythm(s.prose, scene_id=s.id))
        )
    return out


__all__ = [
    "AdverbParagraph",
    "AdverbReport",
    "BurstinessReport",
    "DialogueRhythmReport",
    "adverb_findings",
    "burstiness",
    "burstiness_findings",
    "dialogue_rhythm_findings",
    "scan_adverbs",
    "scan_burstiness",
    "scan_dialogue_rhythm",
    "scan_ir",
]
