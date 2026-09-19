"""叙事传输度 6 维评分 —— 读者「被吸进去多少」的确定性度量。

── 理论出处 ─────────────────────────────────────────────

  Green, M. C., & Brock, T. C. (2000). "The role of transportation in the
  persuasiveness of public narratives." *Journal of Personality and Social
  Psychology*, 79(5), 701–721.
  —— 叙事传输（narrative transportation）是一个可测量的构念：读者同时被
     **注意**、**意象**、**情感**卷入故事世界的程度。它可预测信念改变与
     态度迁移，因此不是文青词汇，而是可操作指标。

  Loewenstein, G. (1994). "The psychology of curiosity: A review and
  reinterpretation." *Psychological Bulletin*, 116(1), 75–98.
  —— **信息缺口理论**：好奇心不是「信息越多越强」，而是来自「已知」与
     「想知道」之间那道被**明确感知**到的缝。缝被当场填平，驱力即消失。
     这是下面「零未解释也是缺陷」那一条的**直接依据**，不是口味偏好。

  Barthes, R. (1968). "L'effet de réel." *Communications* 11, 84–89.
  —— 感官细节是「世界在场」的证据（与 `keel/audit/craft.py` 同源）。

── 公式与两个结构性洞察 ─────────────────────────────────

    传输度 = 0.30×感官细节 + 0.20×对话比例 + 0.15×句长变异
           + 0.15×视角一致性 + 0.10×未解释密度 + 0.10×打断率

**洞察一：太少未解释也是缺陷。** `unexplained == 0` 得 **30 分**，不是满分。
一个把一切都当场解释清楚的故事没有拉力 —— 读者没有可以 lean 进去的开放
问题（Loewenstein 的信息缺口）。Keel 既有的 `anti_slop` / `craft` 只惩罚
「坏」与「平」，**从不奖励留白**；本模块第一次把它变成显式扣分项。
推论：**「最干净的可能文本」不可能是最高分**（未解释 = 30 时总分上限
= 0.9×100 + 0.1×30 = 93）。这个反转是本模块存在的理由。

**洞察二：句长变异是「带」，不是单调指标。**
    sentence_variety = 100 − |CV − 0.7| × 100
CV ≈ 0.7 最好；**太低（句长齐平、节奏单调）与太高（长短乱跳、节奏失序）
都要扣分**。任何「CV 越高越好」的单调实现都是错的。

── 关于六个权重：它们是**先验**，不是科学常数 ─────────────

必须把话说清楚：上式的六个权重（0.30 / 0.20 / 0.15 / 0.15 / 0.10 / 0.10）
**没有任何引用来源**。Green & Brock 测量的是传输度这个构念本身，没有给出
六维加权公式；Loewenstein 只论证「信息缺口驱动好奇」，不涉及权重数值。
这些数字是**设计选择**，是 `DEFAULT_WEIGHTS` 里一组可调的默认值。

因此本模块：
  * 不把它们写成「学术加权公式」，也不虚构出处；
  * 只断言权重之和为 1、且每个维度都能被单独解释与复算；
  * 把权重集中在一个具名常量块里，方便按实际稿件调整。

同理，`SENTENCE_CV_TARGET = 0.7`、`SENSORY_TARGET_PER_SENTENCE = 1.0` 等
靶值也是先验，不是测量得到的常数。

── 与既有模块的关系（刻意不重复的部分）──────────────────

  * **不抄源项目的 20 词感官表**（太粗）。本模块的 `_SENSE_CHANNELS` 按
    **五感通道**组织（视 / 听 / 触 / 嗅 / 味），比扁平词表更可解释；
    与 `craft.py` 的 `_SENSE_WORDS` 用途不同 —— 后者判「有没有可感通道」
    （Barthes 现实效应，布尔味），本模块判「感官细节的**密度**」。
    本项目其余 audit 模块同样是各带各的词表（`dress._PARTICLES` /
    `anti_slop._CLICHE`），此处沿用同一惯例。
  * **不抄源项目的 `open_questions`**（它只是数 `len("？")`）。本模块的
    `scan_ir` 未解问题数取自 Keel 自己的 `Enigma` 状态机（Barthes 阐释
    符码：posed → delayed → partial → resolved → abandoned）；`score(text)`
    在没有台账时用一个**疑问构式**探测器作降级代理，且**明确不数裸问号**。

── 确定性 ───────────────────────────────────────────────

全程纯规则：字符计数、正则、`statistics`。无 LLM、无向量嵌入、无随机数。
同一输入两次必然得到同一个 `TransportationScore`。

── 已知局限（写出来，不藏着）────────────────────────────

  * **视角一致性只看人称代词**：第一人称（我 / 俺 / 咱）与第三人称
    （他 / 她 / 它 / 祂）的**字符计数比**。第二人称（你）不参与 —— 汉语
    叙述里「你」多为呼语而非视角标记。对话段（引号内）整体剔除，否则两人
    正常对话会被误判为视角跳变。
  * **切句是字符级的**：只按终结标点与换行切，逗号不切（逗号是句内节奏）。
    无分词、无句法。
  * **打断率用标点近似**：破折号与省略号被当作「被打断」的代理。它测的是
    「文本里有没有那种抢话/断掉的节奏」，不是真的检测说话人交叠。
  * **未解释的文本代理会漏**：`count_open_questions` 只认少数疑问构式，
    隐性的悬念（不说破的暗示）它看不见。有 IR 时请一律走 `scan_ir`，
    以 `Enigma` 台账为准 —— 文本代理只是台账缺席时的降级路径。
  * **阈值是产品决策**：`DEFAULT_MIN_OVERALL = 60.0` 只是保守默认，应当由
    作者按实际稿件调整，而不是当成物理常数。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, fields

from ..ir.enums import EnigmaState, Severity
from ..validators.base import Finding

# ===========================================================================
# 常量：权重与靶值
# ===========================================================================

#: 六维权重。**这是可调的先验，不是测量得到的科学常数。**
#:
#: 源项目把它们写成「学术加权公式」，但没有任何引用来源 —— 本模块如实标注：
#: 数字是设计选择。改动它们只需改这一处；`_self_check()` 会断言键与
#: `TransportationScore` 的字段一一对应，且和恰为 1。
DEFAULT_WEIGHTS: dict[str, float] = {
    "sensory": 0.30,
    "dialogue": 0.20,
    "sentence_variety": 0.15,
    "pov_consistency": 0.15,
    "unexplained": 0.10,
    "interruption": 0.10,
}

#: 句长变异的目标带中心。CV = 0.7 最好，两侧都扣分（洞察二）。
SENTENCE_CV_TARGET = 0.7

#: 感官细节的饱和点：每句 1 个感官命中即满分。
SENSORY_TARGET_PER_SENTENCE = 1.0

#: 对话比例的饱和点：半数句子含对话即满分。
DIALOGUE_TARGET_RATIO = 0.5

#: 打断率的饱和点：每句 0.5 个打断标记即满分。
INTERRUPTION_TARGET_PER_SENTENCE = 0.5

#: 视角混用的容差：第一/第三人称占比差距在此之内视为一致。
POV_MIX_TOLERANCE = 0.1

#: **洞察一**：零个未解问题时的得分。刻意不是 100 —— 见模块 docstring。
ZERO_UNEXPLAINED_SCORE = 30.0

#: 未解问题的目标带（闭区间，单位：个）。带内满分。
UNEXPLAINED_BAND = (1, 3)

#: 超出目标带后每个未解问题扣多少分。
UNEXPLAINED_DECAY = 10.0

#: 未解问题过剩时的得分地板（过载 = 读者抓不住主线）。
UNEXPLAINED_FLOOR = 20.0

#: `scan_ir` 的默认门限：总分低于它产出一条 WARN。
DEFAULT_MIN_OVERALL = 60.0

# ===========================================================================
# 词表与切分
# ===========================================================================

#: 切句：只按终结标点与换行切。逗号是**句内**节奏信号，不切。
_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")

#: 感官通道词表。按**五感**组织 —— 比扁平的 20 词表更可解释：
#: 缺的是哪一路感官，一眼看得出来。全部为多字词，降低子串误报。
_SENSE_CHANNELS: dict[str, tuple[str, ...]] = {
    "视觉": (
        "光亮", "昏黄", "惨白", "血红", "漆黑", "幽暗", "明亮",
        "微光", "闪烁", "影子", "雾气",
    ),
    "听觉": (
        "声响", "声音", "吱呀", "咔哒", "嗡鸣", "轰鸣",
        "寂静", "嘈杂", "脚步", "喘息",
    ),
    "触觉": (
        "冰凉", "冰冷", "滚烫", "潮湿", "干裂", "粗糙",
        "黏腻", "发麻", "刺痛", "温热", "灼热", "寒意",
    ),
    "嗅觉": ("香气", "恶臭", "腥味", "霉味", "焦味", "刺鼻", "气味", "味道"),
    "味觉": ("苦涩", "甘甜", "酸涩", "咸味", "辛辣"),
}

#: 对话标记（成对与单侧都算）。
_DIALOGUE_MARKS: tuple[str, ...] = ("「", "」", "『", "』", "“", "”", "\"", "'")

#: 对话**配对**，用于把引号内的内容从「叙述」里剔除（视角一致性用）。
_DIALOGUE_PAIRS: tuple[tuple[str, str], ...] = (
    ("「", "」"),
    ("『", "』"),
    ("“", "”"),
    ("‘", "’"),
)

#: 打断标记：破折号（一个或多个）与省略号（含 ASCII 三点）。
_INTERRUPT_RE = re.compile(r"—+|…+|\.{3,}")

#: 第一人称代词字符（字符级计数，故「我们」「咱们」自动覆盖）。
_FIRST_PERSON: frozenset[str] = frozenset("我俺咱")
#: 第三人称代词字符（「他们」「她们」自动覆盖）。
_THIRD_PERSON: frozenset[str] = frozenset("他她它祂")

#: 未解问题的**疑问构式**（降级代理）。
#:
#: ⚠️ 刻意**不数裸问号**。源项目的 `open_questions` 只是 `len("？")`，
#: 它把修辞性反问、清单式提问、对话里的寒暄全部算成「悬念」。
#: 这里只认那些**真的在提出一个未被回答的问题**的构式。
_OPEN_Q_MARKERS: tuple[str, ...] = (
    "为什么", "为何", "怎么会", "究竟", "是谁", "是什么",
    "什么原因", "说不清", "说不明白", "未解", "谜团",
)


def _compile_words(words) -> re.Pattern[str]:
    """把字面量词表编译成一条交替正则（长词优先，避免短词吃掉长词）。"""
    ordered = sorted(set(words), key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in ordered))


_SENSE_RE = _compile_words(
    [w for ws in _SENSE_CHANNELS.values() for w in ws]
)
_OPEN_Q_RE = _compile_words(_OPEN_Q_MARKERS)


# ===========================================================================
# 基础工具
# ===========================================================================


def _sentences(text: str) -> list[str]:
    """切句。按终结标点与换行切，逗号不切。"""
    return [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]


def _strip_dialogue(text: str) -> str:
    """剔除引号内的内容，只留叙述。

    视角一致性必须只看叙述：对白里的「我」是**角色在说话**，不是叙述者
    在用人称。不剔除的话，任何两人的正常对话都会被判成视角跳变。
    """
    for opener, closer in _DIALOGUE_PAIRS:
        text = re.sub(
            re.escape(opener) + ".*?" + re.escape(closer), " ", text, flags=re.S
        )
    return text


def _cv(values: list[int]) -> float:
    """总体变异系数 = 总体标准差 / 均值。样本不足或均值为 0 时返回 0。

    用总体标准差（`pstdev`）：这里的「总体」就是这段文本的全部句子，
    不是从更大的句子池里抽样，故无需 Bessel 修正（与 `dress.py` 一致）。
    """
    if not values:
        return 0.0
    mean = statistics.fmean(values)
    if not mean:
        return 0.0
    return statistics.pstdev(values) / mean


# ===========================================================================
# 六维：各自独立、可单独调用、可单独断言
# ===========================================================================


def sensory_score(text: str) -> float:
    """感官细节 ∈ [0, 100]：感官命中密度 / 句，靶 1.0 命中/句。

    只测**密度**，不测通道覆盖 —— 一个场景反复写「冰凉」也算感官充分。
    这是有意的取舍：通道覆盖会引入第二组权重，而权重越多越像伪科学。
    """
    sents = _sentences(text)
    if not sents:
        return 0.0
    hits = len(_SENSE_RE.findall(text))
    density = hits / len(sents)
    return min(100.0, density / SENSORY_TARGET_PER_SENTENCE * 100.0)


def dialogue_score(text: str) -> float:
    """对话比例 ∈ [0, 100]：含对话标记的句子占比 / 靶 0.5。

    单侧标记（只有「」的左半边）也算 —— 中文排版里对话常跨段，
    右半边可能落在下一句。宁可多算，不可漏算。
    """
    sents = _sentences(text)
    if not sents:
        return 0.0
    with_dialogue = sum(
        1 for s in sents if any(m in s for m in _DIALOGUE_MARKS)
    )
    ratio = with_dialogue / len(sents)
    return min(100.0, ratio / DIALOGUE_TARGET_RATIO * 100.0)


def sentence_variety_score(text: str) -> float:
    """句长变异 ∈ [0, 100]：**目标带**，不是单调指标。

        sentence_variety = 100 − |CV − 0.7| × 100

    CV = 0.7 → 100；CV = 0（句长齐平）→ 30；CV ≥ 1.7 → 0（触底）。
    两侧都扣分：太低是节奏单调，太高是节奏失序。
    """
    sents = _sentences(text)
    if not sents:
        return 0.0
    cv = _cv([len(s) for s in sents])
    return max(0.0, min(100.0, 100.0 - abs(cv - SENTENCE_CV_TARGET) * 100.0))


def pov_consistency_score(text: str) -> float:
    """视角一致性 ∈ [0, 100]：叙述中第一/第三人称的混用程度。

    mixing = min(f, t) / max(f, t)，f / t 为叙述里第一 / 第三人称代词**字符**
    数（对话已剔除）。

        mixing ≤ 0.1  → 100（一致）
        mixing = 1.0  → 0（1:1 混用，最差）
        1:3           → 74.07

    无人称代词（f = t = 0）→ 100：没有可测的混用，不是「一致」也不是
    「不一致」，取满分以免惩罚了正常的第一人称内心独白式叙述。
    """
    body = _strip_dialogue(text)
    if not body.strip():
        return 0.0
    f = sum(1 for ch in body if ch in _FIRST_PERSON)
    t = sum(1 for ch in body if ch in _THIRD_PERSON)
    hi = max(f, t)
    if hi == 0:
        return 100.0
    mixing = min(f, t) / hi
    if mixing <= POV_MIX_TOLERANCE:
        return 100.0
    penalty = (mixing - POV_MIX_TOLERANCE) / (1.0 - POV_MIX_TOLERANCE)
    return max(0.0, 100.0 * (1.0 - penalty))


def unexplained_score(count: int) -> float:
    """未解释密度 ∈ [0, 100] —— **「太少」与「太多」都扣分**。

        count == 0          → 30   （洞察一：全解释清楚 = 没有拉力）
        1 ≤ count ≤ 3       → 100  （目标带：读者有可 lean 进去的开放问题）
        count > 3           → 100 − (count − 3) × 10，地板 20

    为什么 0 不是满分：见模块 docstring 的 Loewenstein 信息缺口理论。
    为什么过剩也扣分：未解问题堆到十几个，读者抓不住主线，悬念变成噪声。
    """
    n = max(0, count)
    if n == 0:
        return ZERO_UNEXPLAINED_SCORE
    lo, hi = UNEXPLAINED_BAND
    if lo <= n <= hi:
        return 100.0
    return max(UNEXPLAINED_FLOOR, 100.0 - (n - hi) * UNEXPLAINED_DECAY)


def interruption_score(text: str) -> float:
    """打断率 ∈ [0, 100]：破折号 / 省略号密度 / 句，靶 0.5 个/句。

    打断是「活人对活人说话」的节奏证据：抢话、截断、话没说完。
    注意 `—+` 与 `…+` 都是量词形式，故「——」只算**一次**打断，不是两次。
    """
    sents = _sentences(text)
    if not sents:
        return 0.0
    hits = len(_INTERRUPT_RE.findall(text))
    density = hits / len(sents)
    return min(100.0, density / INTERRUPTION_TARGET_PER_SENTENCE * 100.0)


def count_open_questions(text: str) -> int:
    """文本里的未解问题数 —— **疑问构式**计数，不是问号计数。

    这是 `Enigma` 台账缺席时的降级代理。有 IR 时请走 `scan_ir`，
    以台账为准（`open_questions_at`）。刻意不数「？」：见 `_OPEN_Q_MARKERS`。

    计数的是**疑问位置**，不是构式出现次数：相邻或重叠的构式合并为一处。
    「究竟是谁」只算**一个**问题 —— 否则同一句话里的两个构式会被记成
    两个悬念，把未解释密度凭空翻倍。
    """
    loci = 0
    last_end = -1
    for m in _OPEN_Q_RE.finditer(text):
        start, end = m.span()
        if start > last_end:  # 与上一处不相邻、不重叠 → 新的一处
            loci += 1
        last_end = max(last_end, end)
    return loci


# ===========================================================================
# 汇总
# ===========================================================================


@dataclass(frozen=True)
class TransportationScore:
    """一段文本的六维传输度体检。

    六个维度都是 0–100 的标量。`overall` 是**属性**而不是存储字段 ——
    这样任何一份报告都不可能持有与公式不一致的结论（与 `dress.py` 同法）。
    """

    sensory: float
    dialogue: float
    sentence_variety: float
    pov_consistency: float
    unexplained: float
    interruption: float

    @property
    def overall(self) -> float:
        """加权总分 ∈ [0, 100]。权重是 `DEFAULT_WEIGHTS` 里的先验。"""
        return (
            DEFAULT_WEIGHTS["sensory"] * self.sensory
            + DEFAULT_WEIGHTS["dialogue"] * self.dialogue
            + DEFAULT_WEIGHTS["sentence_variety"] * self.sentence_variety
            + DEFAULT_WEIGHTS["pov_consistency"] * self.pov_consistency
            + DEFAULT_WEIGHTS["unexplained"] * self.unexplained
            + DEFAULT_WEIGHTS["interruption"] * self.interruption
        )

    def render(self) -> str:
        return (
            f"传输度 {self.overall:.1f}/100 "
            f"= 感官 {self.sensory:.0f} · 对话 {self.dialogue:.0f}"
            f" · 句长带 {self.sentence_variety:.0f}"
            f" · 视角 {self.pov_consistency:.0f}"
            f" · 未解释 {self.unexplained:.0f}"
            f" · 打断 {self.interruption:.0f}"
        )


def score(text: str, *, open_questions: int | None = None) -> TransportationScore:
    """给一段文本打分。

    `open_questions` 是未解问题数：
      * 显式传入（`scan_ir` 走这条，取自 `Enigma` 台账）—— 权威来源；
      * 传 `None` —— 退回 `count_open_questions` 的文本代理（降级路径）。

    空文本 → 六维全零（**不是「完美」，是「没测」** —— 与
    `validators/base.py` 的「SKIPPED ≠ PASS」原则一致）。
    """
    if not text.strip():
        return TransportationScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    n = count_open_questions(text) if open_questions is None else max(0, open_questions)
    return TransportationScore(
        sensory=sensory_score(text),
        dialogue=dialogue_score(text),
        sentence_variety=sentence_variety_score(text),
        pov_consistency=pov_consistency_score(text),
        unexplained=unexplained_score(n),
        interruption=interruption_score(text),
    )


# ===========================================================================
# IR 层：未解问题取自 Enigma 台账
# ===========================================================================


def open_questions_at(ir, scene_id: str) -> int:
    """该场次时刻**仍然悬置未解**的谜题数。

    口径：谜题在「本场或更早」（按话语顺序 sjuzhet）提出，且
    在「本场或更早」尚未解消/遗弃。即「此刻读者心里挂着几个问号」。

    刻意不复用源项目的「数问号」—— Keel 的 `Enigma` 状态机
    （posed → delayed → partial → resolved → abandoned）严格优于它。
    """
    order = {s.id: i for i, s in enumerate(ir.ordered_scenes())}
    here = order.get(scene_id)
    if here is None:
        return 0
    count = 0
    for e in ir.enigmas:
        if e.state in (EnigmaState.RESOLVED, EnigmaState.ABANDONED):
            continue
        planted = order.get(e.planted_at_scene)
        if planted is None or planted > here:
            continue
        if e.resolved_at_scene is not None:
            resolved = order.get(e.resolved_at_scene)
            if resolved is not None and resolved <= here:
                continue
        count += 1
    return count


def scan_ir(ir, *, threshold: float = DEFAULT_MIN_OVERALL) -> list[Finding]:
    """扫描整个 IR 的已写场景，产出传输度结论。

    流程：
      1. 收集所有有 `prose` 的场景（按话语顺序）
      2. 逐场：`open_questions_at` 取台账里的未解问题数
      3. 未解问题为 0 → 一条 `audit:over_explained`（**洞察一**落地）
      4. 总分 < threshold → 一条 `audit:transportation`

    严重度取 WARN：传输度是**工艺/沉浸**信号，不是结构性错误 ——
    真正的结构门禁在 `keel/validators/` 里（与 `craft.py` / `dress.py`
    的严重度政策一致）。零未解释取 WARN 而非 INFO，是因为本模块的核心
    主张就是「它也是缺陷」；结局场次里它可能是有意为之，故文案里说明。

    无正文 → 返回空。**空返回 ≠ 通过**：调用方应把「无正文」单独记为
    SKIPPED（与 `validators/base.py` 的原则一致）。
    """
    scenes = [s for s in ir.ordered_scenes() if s.prose]
    if not scenes:
        return []

    out: list[Finding] = []
    for s in scenes:
        n_open = open_questions_at(ir, s.id)
        rep = score(s.prose, open_questions=n_open)

        if n_open == 0:
            out.append(
                Finding(
                    code="audit:over_explained",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message=(
                        "本场没有悬置未解的问题（未解释 = 0）→ 该维仅得 "
                        f"{ZERO_UNEXPLAINED_SCORE:.0f}/100："
                        "当场把一切解释清楚的故事，读者没有可 lean 进去的开放问题"
                    ),
                    suggestion=(
                        "留一个**本场不回答**的问题（人物不知道答案、"
                        "或读者知道而人物不知道），让读者带着它往下读。"
                        "若这是结局场次，刻意收束全部线索，可忽略本条"
                    ),
                    evidence={
                        "open_questions": 0,
                        "unexplained": rep.unexplained,
                        "overall": round(rep.overall, 4),
                    },
                )
            )

        if rep.overall < threshold:
            out.append(
                Finding(
                    code="audit:transportation",
                    severity=Severity.WARN,
                    scene_id=s.id,
                    message=(
                        f"叙事传输度偏低：{rep.overall:.1f}/100 < {threshold:.0f}"
                        f"（感官 {rep.sensory:.0f} · 对话 {rep.dialogue:.0f}"
                        f" · 句长带 {rep.sentence_variety:.0f}"
                        f" · 视角 {rep.pov_consistency:.0f}"
                        f" · 未解释 {rep.unexplained:.0f}"
                        f" · 打断 {rep.interruption:.0f}）"
                    ),
                    suggestion=(
                        "逐维排查：感官低 → 补可感的具体物；对话低 → 让角色开口；"
                        "句长带低 → 检查是句长齐平还是长短乱跳；"
                        "视角低 → 叙述里第一/第三人称混用；"
                        "未解释 30 → 本场没有任何悬置的问题；"
                        "打断低 → 对话过于工整，缺抢话与截断"
                    ),
                    evidence={
                        "overall": round(rep.overall, 4),
                        "threshold": threshold,
                        "sensory": round(rep.sensory, 4),
                        "dialogue": round(rep.dialogue, 4),
                        "sentence_variety": round(rep.sentence_variety, 4),
                        "pov_consistency": round(rep.pov_consistency, 4),
                        "unexplained": round(rep.unexplained, 4),
                        "interruption": round(rep.interruption, 4),
                        "open_questions": n_open,
                    },
                )
            )
    return out


# ---------------------------------------------------------------------------
# 开发期自检
# ---------------------------------------------------------------------------


def _self_check() -> None:
    """`DEFAULT_WEIGHTS` 必须与 `TransportationScore` 的字段一一对应，且和为 1。

    防的是「加了维度却忘了加权重」—— 那样该维度会静默地不参与总分，
    正是本模块（以及 `dress.py` 的 `_self_check`）要消灭的那类静默失败。
    """
    declared = {f.name for f in fields(TransportationScore)}
    assert declared == set(DEFAULT_WEIGHTS), (
        f"DEFAULT_WEIGHTS 与 TransportationScore 字段不一致："
        f"{declared ^ set(DEFAULT_WEIGHTS)}"
    )
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9, "权重之和必须为 1"


_self_check()


__all__ = [
    "DEFAULT_MIN_OVERALL",
    "DEFAULT_WEIGHTS",
    "DIALOGUE_TARGET_RATIO",
    "INTERRUPTION_TARGET_PER_SENTENCE",
    "POV_MIX_TOLERANCE",
    "SENSORY_TARGET_PER_SENTENCE",
    "SENTENCE_CV_TARGET",
    "TransportationScore",
    "UNEXPLAINED_BAND",
    "UNEXPLAINED_DECAY",
    "UNEXPLAINED_FLOOR",
    "ZERO_UNEXPLAINED_SCORE",
    "count_open_questions",
    "dialogue_score",
    "interruption_score",
    "open_questions_at",
    "pov_consistency_score",
    "scan_ir",
    "score",
    "sensory_score",
    "sentence_variety_score",
    "unexplained_score",
]
