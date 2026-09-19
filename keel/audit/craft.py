"""四个工艺检测器 —— 张力 / 控制感 / 现实效应 / 展示不告知。

与 `anti_slop.py` 的关系：反 slop 查的是**句子层面的模板化**（否定式煽情、
排比、陈词滥调）。本模块查的是**段落层面的工艺缺陷** —— 张力被自己抵消、
叙事失去控制感、世界没有质感、情绪被直接告知。两者互补，不重叠。

── 四份出处 ─────────────────────────────────────────────

  micro_tension     Donald Maass《Writing the Breakout Novel》。
                    Maass 的主张：张力不是「情节里有没有冲突」，而是**每一段
                    都要有未解决的摩擦**（micro-tension）。他同时点名了一个
                    反模式：刚拉起的张力被同一段里的流水账/静态描写中和掉 ——
                    本模块把它实现为 `self_cancellation`。

  control_illusion  Peter Storr 的六条叙事控制规则。违反任何一条，读者的感受
                    不是「角色失控」而是「**故事**失控」：
                      因果解释延迟 / 模式中断 / 视角跳变 /
                      信息超载 / 无回报 / 细节缺失

  reality_effect    Roland Barthes「L'effet de réel」(Communications 11, 1968)。
                    让读者相信虚构世界的不是意义，是那些**无意义的、具体的、
                    感官的**细节（他举的例子是福楼拜房间里那具不参与情节的
                    晴雨表）。抽象名词堆砌 = 意义过载而世界缺席。

  show_dont_tell    展示不告知（show, don't tell）。本模块唯一**必须做豁免**
                    的检测器，见下。

── show_dont_tell 为什么不是纯命中匹配 ────────────────────

`anti_slop._EMOTION_TELLING` 是纯命中匹配：只要出现「他感到愤怒」就报警。
问题是「他很生气，攥紧的拳头砸在桌上」也是命中 —— 而这句**恰好是正确写法**。
纯命中匹配会把合格文本报成缺陷，于是它的输出会被人整体忽略，
一个会被整体忽略的门禁等于没有门禁。

所以本检测器分三步：

    1. 检出直述，并判定它属于哪一类情绪（`_TELL_GROUPS`）
    2. 在**邻域**（同句 + 前后各 `window` 句，默认 1）里找该类情绪的
       **呈现信号**（`_SHOW_SIGNALS`，如「愤怒」→ 攥紧 / 青筋 / 拍桌 / 摔 …）
    3. **找得到 → 豁免，不报**；只有找不到才产出 Finding

即：本检测器回答的问题是「情绪被**告知**了，而且**没有被展示**」，
而不是「出现了情绪词」。这个非对称是它的全部价值所在，
`tests/test_craft.py` 第 4/5 组用同一句直述配两种邻句来钉死它。

── 词表的来源与许可证红线（法律要求，不是形式）────────────

**本模块所有词表与阈值都是 Keel 自己从上述四份方法论推导出来的构造，
没有复制任何第三方门禁文件的内容。** 具体地：

  * 不复制 InkOS（AGPL-3.0）的任何词表、阈值或代码；
  * 不复制任何其他引擎的 gate / 词表文件；
  * 各词表是从上面点名的出处逐条推导的（Maass 的张力形态、Storr 的六条规则、
    Barthes 的具体/抽象对立、show-don't-tell 的身体反应清单），
    推导过程写在各词表上方的注释里，可被逐条复核。

理由：「工程模式」可以借鉴，「内容 / 词表 / 阈值」不能 —— 后者的著作权归属
清楚，抄进来就等于把别人的许可证义务带到本项目上。

── 严重度政策 ───────────────────────────────────────────

工艺信号天然有噪声（人类作者也会写出「张力密度低」的段落，而且常常是**故意**的：
留白、呼吸、节奏缓冲）。因此与 `anti_slop.py` 一致：

  * **默认 INFO** —— 单次命中只做通报：**不影响 `Report.passed()`**（只看 ERROR），
    但**会**让 `Report.score()` 扣 1 分
    （`score = 100 - 12×ERROR - 4×WARN - 1×INFO`，见 `validators/base.py`）。
    实测：本模块在两条干净基线上各产出 6 条 INFO，即健康分 −6
    （novel 95→89 · micro_drama 94→88）。**这个扣分是既有的统一规则**
    （`anti_slop` 的 INFO 同样扣分），不是本模块引入的 —— 但读到这里的人
    应当知道「INFO 不影响判断」这句话**只对 passed() 成立，对 score() 不成立**；
  * **只在明确量化的阈值上升级为 WARN** —— 同一条规则在一段里命中 N 次
    （各检测器的 N 写在 `_WARN_AT` / 模块常量里）、或两个阈值同时满足
    （如自我抵消要求张力信号 ≥2 **且**平淡材料 ≥2）。

不产出 ERROR：工艺缺陷是**品味判断**，不是结构性错误。真正该阻断的是
`keel/validators/` 里的结构门禁，不是这里。

> **待决问题（未擅自改动）**：`score()` 的语义是「结构健康分」，而本模块与
> `anti_slop` 都是**非结构性**信号，却按统一规则扣同一个分。这意味着
> 「健康分」实际混入了工艺噪声。三条出路——(a) 维持现状，接受混入；
> (b) 让 INFO 不扣分（则两条基线回到 100，但 README/verify.py 记录的数字要同步改）；
> (c) 把工艺项从结构分里拆出来单列。**这是产品决策，留给作者定。**

── 已知局限（写出来，不藏着）────────────────────────────

  * **纯规则，无句法**：所有规则都是词表 / 正则 / 计数，没有分词也没有句法树。
    「因果解释延迟」只能靠显式标记（「至于为什么」「后来才知道」）捕捉，
    隐式的因果悬置（写了一大段因果但就是不交代动机）抓不到。
  * **模式中断是近似**：用「连续 ≥3 句句首二字相同、随后被打破」近似
    Storr 说的「建立了模式又无信号地中断它」。重复句首也可能只是刻意排比。
  * **视角跳变只认人称代词**：没有人物名册就认不出「张三…李四…张三」，
    只认他/她/它/我/你。两人的正常对话场景会被误报为视角跳变（故为 INFO）。
  * **现实效应只做词频比**：Barthes 的现实效应是**语义**概念（细节「无意义」），
    本模块只能比抽象名词与可感具体词的**数量比**。它筛的是「该不该多看两眼」，
    不是判决。
  * **细节缺失只认感官通道**：`_SENSE_WORDS` 是感官通道词（冷热/声响/气味…），
    不是全部具体名词。「他拿起杯子」里的「杯子」不算感官细节 ——
    因为缺的是**可感的通道**，不是物件本身。
  * **统计粒度是选过的，不是随手定的**：`micro_tension` / `reality_effect` /
    `info_overload` 逐**段**判，`no_payoff` / `missing_detail` / `pov_jump`
    逐**场**判。理由：抽象过载、张力中和、信息堆砌都是**局部**现象，
    整场求和会让一个坏段落被其余段落摊平（这是拿真实段落跑出来的修正，
    见 `RealityParagraph` 的注释）；而「抛出的问题有没有回收」天然跨段，
    「这场戏有没有可感细节」问的是整场。**逐场判的两项因此有一个已知盲区：
    一场里只要有一段感官充足，其余段落的细节缺失就被掩盖。** 这是取舍，
    不是待修的 bug —— 改成逐段会让每一个短动作段都报警，噪声大于收益。
  * **中文分词不做**：所有匹配都是子串匹配，因此单字词表（如「走」「坐」）
    会在复合词里误命中。这是有意取舍：误报在 INFO 级别可接受，
    引入分词则要新增依赖，违反零依赖铁律。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..ir.enums import Severity
from ..validators.base import Finding

# ---------------------------------------------------------------------------
# 共用：切分与计数
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")


def _sentences(text: str) -> list[str]:
    """切句。只按终结标点与换行切，不在逗号处切 —— 邻域窗口的粒度是「句」。"""
    return [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]


def _paragraphs(text: str) -> list[str]:
    """切段。中文网文一行即一段，故按换行切而不是按空行切。"""
    return [p.strip() for p in re.split(r"\n+", text) if p.strip()]


def _count_res(pats: list[re.Pattern[str]], text: str) -> tuple[int, str]:
    """统计一组正则的总命中数，并返回第一个样本。"""
    total = 0
    sample = ""
    for p in pats:
        found = p.findall(text)
        if found:
            total += len(found)
            if not sample:
                sample = found[0] if isinstance(found[0], str) else str(found[0])
    return total, sample


def _compile_all(groups: dict[str, tuple[str, ...]]) -> list[re.Pattern[str]]:
    """把一组字面量词表编译成一条交替正则（长词优先，避免短词吃掉长词）。"""
    words = sorted({w for ws in groups.values() for w in ws}, key=len, reverse=True)
    return [re.compile("|".join(re.escape(w) for w in words))]


#: 感官通道词：**通道**，不是物件。缺的是可感的通道，不是东西本身。
#: 被两个检测器共用（故放在共用区，不埋在某个检测器里）：
#:   reality_effect   —— 它是 Barthes 意义上「世界在场」的正证据；
#:   control_illusion —— 「细节缺失」判它**缺席**（有动作但没有任何通道）。
_SENSE_WORDS: tuple[str, ...] = (
    "冰凉", "冰冷", "滚烫", "潮湿", "湿", "干裂", "粗糙", "黏", "刺鼻",
    "腥", "霉", "焦", "香", "臭", "响", "吱", "咔", "嗡", "轰", "静",
    "光", "暗", "影", "亮", "凉", "烫", "冷", "热", "疼", "麻", "痒",
)

_SENSE_RES = _compile_all({"sense": _SENSE_WORDS})


# ===========================================================================
# 1. micro_tension —— Maass《Writing the Breakout Novel》
# ===========================================================================

#: 张力信号（Maass 的 micro-tension 形态：每句话里那点未解决的摩擦）。
#: 逐类推导自他对「什么让读者想读下一句」的列举：对立、不确定、威胁、
#: 时限、隐瞒、身体反应、追问。
_TENSION_GROUPS: dict[str, tuple[str, ...]] = {
    "对立": ("却", "但", "可是", "然而", "偏偏", "反倒"),
    "不确定": ("也许", "或许", "难道", "莫非", "万一", "不确定", "说不准"),
    "威胁": ("刀", "血", "死", "杀", "追", "逃", "危险", "威胁", "伤口", "疼"),
    "时限": ("立刻", "马上", "来不及", "只剩", "赶紧", "必须", "再不", "当即"),
    "隐瞒": ("秘密", "隐瞒", "不能说", "藏着", "不敢说", "装作"),
    "身体反应": ("心跳", "冷汗", "颤抖", "攥紧", "窒息", "喉咙发紧", "喘"),
    "追问": ("？", "?", "吗", "呢"),
}

#: 平淡材料（张力中和剂）。Maass 点名的反模式：把刚拉起的张力交给
#: 流水账 / 静态描写 / 概述 / 模糊限定词去消化，读者的紧张感随之漏光。
_FLAT_GROUPS: dict[str, tuple[str, ...]] = {
    "流水账": ("然后", "接着", "随后", "于是", "之后", "再后来", "于是乎"),
    "静态": ("一切", "如常", "照旧", "一如既往", "平静", "无事", "日子", "依旧", "仍然是"),
    "概述": ("感到很", "觉得有些", "总的来说", "总之", "毕竟是", "无非是"),
    "模糊": ("似乎", "好像", "大概是", "差不多", "有点"),
}

_TENSION_RES = _compile_all(_TENSION_GROUPS)
_FLAT_RES = _compile_all(_FLAT_GROUPS)

#: 低密度阈值（张力信号 / 句）。取 0.15 而不是更高：一句里带一个信号
#: 就是 Maass 说的合格线，0.15 只筛「整段几乎没有摩擦」的段落。
_TENSION_LOW_DENSITY = 0.15
#: 少于 2 句的段落不做密度判断 —— 一句话的密度不是密度。
_TENSION_LOW_MIN_SENTENCES = 2
#: 自我抵消的双阈值：两类材料**同时**达标才算互相中和（量化，故可升 WARN）。
_CANCEL_TENSION_MIN = 2
_CANCEL_FLAT_MIN = 2


@dataclass
class ParagraphTension:
    """一段的张力体检。"""

    index: int
    sentence_count: int
    tension_count: int
    flat_count: int
    tension_sample: str
    flat_sample: str

    @property
    def density(self) -> float:
        return self.tension_count / self.sentence_count if self.sentence_count else 0.0

    @property
    def low_density(self) -> bool:
        return (
            self.sentence_count >= _TENSION_LOW_MIN_SENTENCES
            and self.density < _TENSION_LOW_DENSITY
        )

    @property
    def self_cancelled(self) -> bool:
        return (
            self.tension_count >= _CANCEL_TENSION_MIN
            and self.flat_count >= _CANCEL_FLAT_MIN
        )


@dataclass
class MicroTensionReport:
    scene_id: str | None
    char_count: int
    paragraphs: list[ParagraphTension] = field(default_factory=list)


def scan_micro_tension(text: str, scene_id: str | None = None) -> MicroTensionReport:
    """逐段统计张力信号密度，并判定「自我抵消」。"""
    if not text.strip():
        return MicroTensionReport(scene_id, 0, [])

    paras: list[ParagraphTension] = []
    for i, para in enumerate(_paragraphs(text)):
        tension, tsample = _count_res(_TENSION_RES, para)
        flat, fsample = _count_res(_FLAT_RES, para)
        paras.append(
            ParagraphTension(
                index=i,
                sentence_count=len(_sentences(para)),
                tension_count=tension,
                flat_count=flat,
                tension_sample=tsample,
                flat_sample=fsample,
            )
        )
    return MicroTensionReport(scene_id, len(text), paras)


def micro_tension_findings(report: MicroTensionReport) -> list[Finding]:
    """把张力报告转成体检项。"""
    out: list[Finding] = []
    for p in report.paragraphs:
        n = p.index + 1
        if p.self_cancelled:
            out.append(
                Finding(
                    code="craft:micro_tension_cancel",
                    severity=Severity.WARN,
                    scene_id=report.scene_id,
                    message=(
                        f"第{n}段张力自我抵消：{p.tension_count} 个张力信号"
                        f"被 {p.flat_count} 处平淡材料中和（{p.flat_sample!r}）"
                    ),
                    suggestion="删掉平淡材料，或把它改写成带阻力的动作；张力留在段末不要收口",
                )
            )
        if p.low_density:
            out.append(
                Finding(
                    code="craft:micro_tension_low",
                    severity=Severity.INFO,
                    scene_id=report.scene_id,
                    message=(
                        f"第{n}段张力密度 {p.density:.2f}/句，偏低"
                        f"（{p.sentence_count} 句仅 {p.tension_count} 个张力信号）"
                    ),
                    suggestion="按 Maass：每句话都该带一点未解决的摩擦，哪怕是角色自己的犹豫",
                )
            )
    return out


# ===========================================================================
# 2. control_illusion —— Peter Storr 的六条叙事控制规则
# ===========================================================================

#: 规则一 因果解释延迟：因果被显式挂起，读者被要求「先接受，别问」。
_CAUSAL_DELAY = [
    r"至于为什么",
    r"为什么[^。！？]{0,8}(?:不说|不提|没提|没有说)",
    r"(?:后来|日后|多年后)才(?:知道|明白|懂)",
    r"说不清",
    r"没有解释",
    r"不知(?:为何|为什么|道为什么)",
    r"暂且(?:不提|不论|放下)",
    r"(?:暂时|暂且)(?:不去想|没多想)",
    r"原因(?:不明|不详|他也不知道)",
]

#: 规则四 信息超载：一段里塞进太多「新的事实」。
_INFO_TOKENS = [
    r"《[^》]{1,12}》",
    r"「[^」]{1,12}」",
    r"“[^”]{1,12}”",
    r"\d+",
    r"[零〇一二两三四五六七八九十百千]{1,6}(?:个|种|道|层|重|条|门|界|纪|年|月|日|里|斤|人)",
    # 顿号枚举（≥3 项）算一处：成串的专名/名目是超载的典型形态
    r"(?:[^，。；！？\n、]{1,12}、){2,}[^，。；！？\n、]{1,12}",
]

#: 规则五 无回报：抛出的问题/伏笔在本文内没有任何回收标记。
_UNRESOLVED = [
    r"究竟",
    r"到底",
    r"为什么",
    r"是谁",
    r"答案(?:是什么|在哪|还没)",
    r"总有一天",
    r"那时.{0,2}不知道",
    r"很久以后",
    r"他记得",
]
_RESOLUTION = [
    r"原来",
    r"终于(?:明白|知道|懂)",
    r"答案(?:是|就)",
    r"真相(?:是|大白)",
    r"这才知道",
    r"解开了",
]

#: 规则六 细节缺失的动作词（用于判断「场景在动，但没有可感的通道」）。
_ACTION_VERBS = ("走", "跑", "说", "看", "拿", "坐", "站", "推", "抓", "转身", "抬头", "低头")

_CAUSAL_DELAY_RES = [re.compile(p) for p in _CAUSAL_DELAY]
_INFO_TOKEN_RES = [re.compile(p) for p in _INFO_TOKENS]
_UNRESOLVED_RES = [re.compile(p) for p in _UNRESOLVED]
_RESOLUTION_RES = [re.compile(p) for p in _RESOLUTION]
_ACTION_RE = _compile_all({"action": _ACTION_VERBS})

#: 升级为 WARN 的量化阈值（命中次数）。低于它一律 INFO。
_WARN_AT: dict[str, int] = {
    "causal_delay": 3,
    "pattern_break": 4,
    "pov_jump": 3,
    "info_overload": 8,
    "no_payoff": 4,
    "missing_detail": 6,
}

_CONTROL_LABELS: dict[str, str] = {
    "causal_delay": "因果解释延迟",
    "pattern_break": "模式中断",
    "pov_jump": "视角跳变",
    "info_overload": "信息超载",
    "no_payoff": "无回报",
    "missing_detail": "细节缺失",
}

_CONTROL_SUGGESTIONS: dict[str, str] = {
    "causal_delay": "把「为什么」的答案给出来，或者干脆删掉这个悬置的因果",
    "pattern_break": "中断前先给一个信号（角色察觉/环境变化），让读者知道是故事在转",
    "pov_jump": "一段只留一个感知者；换视角就换段",
    "info_overload": "拆成多段，每段只给一个新事实；专名先给一个，其余靠后",
    "no_payoff": "本场至少回收一个抛出的问题，否则删掉它",
    "missing_detail": "给一个可感的通道：声音、气味、温度、手上的触感",
}

#: 模式中断：连续多少句句首相同才算「建立了模式」。
_PATTERN_RUN_MIN = 3
#: 视角跳变：一段内主语切换多少次才算「跳」。
_POV_SWITCH_MIN = 2
#: 信息超载：一段内信息标记数阈值。
_INFO_OVERLOAD_MIN = 6
#: 无回报：至少抛出几个未解问题、且没有任何回收标记。
_NO_PAYOFF_MIN_UNRESOLVED = 2
#: 细节缺失：动作词阈值。
_MISSING_DETAIL_MIN_ACTIONS = 3

_POV_PRONOUNS = ("他", "她", "它", "我", "你")


@dataclass
class ControlHit:
    """一条控制感缺陷。每条规则最多一条（count 为该规则在本场内的命中次数）。"""

    rule: str
    label: str
    count: int
    sample: str


@dataclass
class ControlReport:
    scene_id: str | None
    char_count: int
    hits: list[ControlHit] = field(default_factory=list)


def _detect_pattern_break(sentences: list[str]) -> tuple[int, str] | None:
    """规则二 模式中断（近似）。

    建立了模式（连续 ≥3 句句首二字相同）之后**被打破** → 读者感到叙述失去了
    控制。局限见模块 docstring：重复句首也可能只是刻意排比。
    """
    heads = [s[:2] for s in sentences]
    i = 0
    while i < len(heads):
        j = i
        while j + 1 < len(heads) and heads[j + 1] == heads[i]:
            j += 1
        run = j - i + 1
        if run >= _PATTERN_RUN_MIN and j + 1 < len(heads):
            return run, sentences[i]
        i = j + 1
    return None


def _leading_pov(sentence: str) -> str | None:
    head = sentence[:4]
    for p in _POV_PRONOUNS:
        if p in head:
            return p
    return None


def _detect_pov_jump(paragraphs: list[str]) -> tuple[int, str]:
    """规则三 视角跳变：**同一段内**感知者反复横跳。

    只认人称代词（无名册），故两人的正常对话也会命中 —— 因此是 INFO。
    """
    switches = 0
    sample = ""
    for para in paragraphs:
        seq = [p for p in (_leading_pov(s) for s in _sentences(para)) if p]
        prev = None
        for cur in seq:
            if prev is not None and cur != prev:
                switches += 1
                if not sample:
                    sample = cur
            prev = cur
    return switches, sample


def scan_control(text: str, scene_id: str | None = None) -> ControlReport:
    """按 Storr 的六条控制规则扫描一段文本。"""
    if not text.strip():
        return ControlReport(scene_id, 0, [])

    hits: list[ControlHit] = []
    sentences = _sentences(text)
    paragraphs = _paragraphs(text)

    n, s = _count_res(_CAUSAL_DELAY_RES, text)
    if n:
        hits.append(ControlHit("causal_delay", _CONTROL_LABELS["causal_delay"], n, s))

    pb = _detect_pattern_break(sentences)
    if pb:
        hits.append(
            ControlHit("pattern_break", _CONTROL_LABELS["pattern_break"], pb[0], pb[1])
        )

    pj, pjs = _detect_pov_jump(paragraphs)
    if pj >= _POV_SWITCH_MIN:
        hits.append(ControlHit("pov_jump", _CONTROL_LABELS["pov_jump"], pj, pjs))

    # 信息超载是**局部**现象：逐段取最高值，而不是整场求和 ——
    # 整场求和会让一个专名密集的段落被其余段落摊薄。
    info, isample = 0, ""
    for para in paragraphs:
        cnt, sample = _count_res(_INFO_TOKEN_RES, para)
        if cnt > info:
            info, isample = cnt, sample
    if info >= _INFO_OVERLOAD_MIN:
        hits.append(
            ControlHit("info_overload", _CONTROL_LABELS["info_overload"], info, isample)
        )

    unresolved, usample = _count_res(_UNRESOLVED_RES, text)
    resolved, _ = _count_res(_RESOLUTION_RES, text)
    if unresolved >= _NO_PAYOFF_MIN_UNRESOLVED and resolved == 0:
        hits.append(
            ControlHit("no_payoff", _CONTROL_LABELS["no_payoff"], unresolved, usample)
        )

    actions, asample = _count_res(_ACTION_RE, text)
    sense, _ = _count_res(_SENSE_RES, text)
    if actions >= _MISSING_DETAIL_MIN_ACTIONS and sense == 0:
        hits.append(
            ControlHit("missing_detail", _CONTROL_LABELS["missing_detail"], actions, asample)
        )

    return ControlReport(scene_id, len(text), hits)


def control_findings(report: ControlReport) -> list[Finding]:
    """把控制感报告转成体检项。"""
    out: list[Finding] = []
    for h in report.hits:
        sev = Severity.WARN if h.count >= _WARN_AT.get(h.rule, 3) else Severity.INFO
        out.append(
            Finding(
                code=f"craft:control:{h.rule}",
                severity=sev,
                scene_id=report.scene_id,
                message=f"{h.label} ×{h.count}（例：{h.sample!r}）",
                suggestion=_CONTROL_SUGGESTIONS.get(h.rule),
                evidence={"rule": h.rule, "count": h.count},
            )
        )
    return out


# ===========================================================================
# 3. reality_effect —— Barthes「L'effet de réel」
# ===========================================================================

#: 抽象名词：承载「意义」的词。Barthes 的对立面 —— 它们不指涉任何可感之物。
_ABSTRACT_NOUNS: tuple[str, ...] = (
    "命运", "宿命", "意义", "价值", "本质", "存在", "自由", "真理", "灵魂",
    "意志", "情感", "精神", "理智", "道义", "责任", "理想", "信念", "境界",
    "执念", "觉悟", "心境", "气度", "格局", "情怀", "信仰", "原则", "底线",
    "痛苦", "幸福", "孤独", "绝望", "希望", "尊严", "正义", "道德", "意识",
)
#: 抽象名词后缀（低歧义，故可用）。只收这三个：性/度 会把「温度」「个性」
#: 这类可感/具象词也吃进来，故不收。
_ABSTRACT_SUFFIXES: tuple[str, ...] = ("主义", "观念", "精神")

#: 感官通道词表在共用区定义（`_SENSE_WORDS` / `_SENSE_RES`），此处只加具体物。
#: 无意义的具体物（Barthes 的晴雨表本体）：不参与情节，只证明世界存在。
_CONCRETE_NOUNS: tuple[str, ...] = (
    "杯", "窗", "桌", "椅", "门", "墙", "灰", "尘", "锈", "裂缝", "渍", "印",
    "痕", "烟", "灯", "绳", "布", "纸", "笔", "铜", "铁", "石", "木", "土",
    "雨", "雪", "风", "雾", "瓦", "砖", "钉", "锁", "钥匙", "碗", "筷",
    "刀", "鞘", "鞋", "扣", "袖", "领", "袋", "肩", "茧", "扁担",
)

_ABSTRACT_RES = _compile_all({"abstract": _ABSTRACT_NOUNS + _ABSTRACT_SUFFIXES})
_CONCRETE_RES = _compile_all({"concrete": _CONCRETE_NOUNS})
_REALITY_RES = _SENSE_RES + _CONCRETE_RES

#: 抽象词个数达到多少才值得看比值（1-2 个抽象词是正常行文）。
_REALITY_MIN_ABSTRACT = 3
#: 抽象/具体 比值达到多少算「抽象压过可感」。
_REALITY_RATIO = 2.0
#: 升级 WARN 的量化阈值：抽象词够多 **且** 比值够高。
_REALITY_WARN_ABSTRACT = 6
_REALITY_WARN_RATIO = 3.0

#: 具体化建议：把抽象名词换成一个可感的具体物（Barthes 意义上的现实效应）。
#: 建议本身不追求文学质量，只负责指出「这里可以落地」。
_CONCRETISE: dict[str, str] = {
    "命运": "手上的茧、鞋底磨穿的洞",
    "宿命": "同一双鞋走过的同一条路",
    "意义": "他反复摩挲的那枚铜钱",
    "价值": "换来的三枚铜板",
    "本质": "切开后看见的那层纹路",
    "存在": "留在桌面上的那道印子",
    "自由": "门轴转动的声音",
    "真理": "刻在石头上被雨水磨钝的那行字",
    "灵魂": "他熬夜后眼里的红血丝",
    "意志": "咬出齿印的木柄",
    "情感": "袖口上那圈洗不掉的渍",
    "精神": "他熬红的眼睛",
    "责任": "压弯的扁担",
    "理想": "墙上那张卷了边的纸",
    "信念": "贴身带着的那半块瓦片",
    "尊严": "洗得发白的领口",
    "孤独": "桌上多出来的那副碗筷",
    "绝望": "他手心里掐出的月牙印",
    "痛苦": "他一直没敢碰的那道疤",
    "希望": "窗缝里漏进来的一线光",
}


@dataclass
class RealityParagraph:
    """一段的抽象 / 具体词频。

    **逐段而不是逐场** —— 这是拿真实段落跑出来的一处修正。原实现按整场统计，
    结果「命运的意义在于尊严与自由的本质…」这一段（9 个抽象词、0 个具体词）
    被同一场里另一段的「杯子/窗台/灰尘」抵消，比值降到阈值以下 ——
    **本检测器存在的理由那一类段落反而漏报了**。
    抽象过载是**局部**现象：一段的意义堆砌不会被隔壁段的具体物治好。
    """

    index: int
    char_count: int
    abstract_hits: list[str] = field(default_factory=list)
    concrete_hits: list[str] = field(default_factory=list)

    @property
    def abstract_count(self) -> int:
        return len(self.abstract_hits)

    @property
    def concrete_count(self) -> int:
        return len(self.concrete_hits)

    @property
    def ratio(self) -> float:
        """抽象 / 具体。分母 +1 是为了让「零具体词」不炸除零。"""
        return self.abstract_count / (self.concrete_count + 1)

    @property
    def flagged(self) -> bool:
        return (
            self.abstract_count >= _REALITY_MIN_ABSTRACT
            and self.ratio >= _REALITY_RATIO
        )

    @property
    def escalate(self) -> bool:
        return (
            self.abstract_count >= _REALITY_WARN_ABSTRACT
            and self.ratio >= _REALITY_WARN_RATIO
        )


@dataclass
class RealityReport:
    scene_id: str | None
    char_count: int
    paragraphs: list[RealityParagraph] = field(default_factory=list)

    # -- 场级汇总（供调用方一眼看全貌；判据仍是逐段的）--

    @property
    def abstract_hits(self) -> list[str]:
        return [w for p in self.paragraphs for w in p.abstract_hits]

    @property
    def concrete_hits(self) -> list[str]:
        return [w for p in self.paragraphs for w in p.concrete_hits]

    @property
    def abstract_count(self) -> int:
        return len(self.abstract_hits)

    @property
    def concrete_count(self) -> int:
        return len(self.concrete_hits)

    @property
    def ratio(self) -> float:
        return self.abstract_count / (self.concrete_count + 1)

    @property
    def abstract_density(self) -> float:
        """每百字抽象名词数。"""
        return self.abstract_count * 100 / self.char_count if self.char_count else 0.0

    @property
    def concrete_density(self) -> float:
        return self.concrete_count * 100 / self.char_count if self.char_count else 0.0


def _findall(res: list[re.Pattern[str]], text: str) -> list[str]:
    out: list[str] = []
    for p in res:
        out.extend(p.findall(text))
    return out


def scan_reality(text: str, scene_id: str | None = None) -> RealityReport:
    """逐段统计抽象名词与可感具体词，返回现实效应报告。"""
    if not text.strip():
        return RealityReport(scene_id, 0, [])
    return RealityReport(
        scene_id=scene_id,
        char_count=len(text),
        paragraphs=[
            RealityParagraph(
                index=i,
                char_count=len(para),
                abstract_hits=_findall(_ABSTRACT_RES, para),
                concrete_hits=_findall(_REALITY_RES, para),
            )
            for i, para in enumerate(_paragraphs(text))
        ],
    )


def reality_findings(report: RealityReport) -> list[Finding]:
    """逐段判断抽象是否压过可感，给出具体化建议。"""
    out: list[Finding] = []
    for p in report.paragraphs:
        if not p.flagged:
            continue
        a, c, r = p.abstract_count, p.concrete_count, p.ratio
        sev = Severity.WARN if p.escalate else Severity.INFO
        target = next((w for w in p.abstract_hits if w in _CONCRETISE), None)
        if target:
            concrete = _CONCRETISE[target]
            suggestion = f"把「{target}」这类抽象名词换成具体可感的东西：{concrete}"
        else:
            suggestion = "给一个可感的具体物：不参与情节、但能证明这个世界存在"
        out.append(
            Finding(
                code="craft:reality_effect",
                severity=sev,
                scene_id=report.scene_id,
                message=(
                    f"第{p.index + 1}段抽象名词 {a} 处 vs 可感具体词 {c} 处，"
                    f"比值 {r:.1f}：意义压过了世界"
                    f"（例：{'、'.join(p.abstract_hits[:3])}）"
                ),
                suggestion=suggestion,
                evidence={"paragraph": p.index, "abstract": a, "concrete": c, "ratio": round(r, 2)},
            )
        )
    return out


# ===========================================================================
# 4. show_dont_tell —— 展示不告知（检测 + 豁免）
# ===========================================================================

#: 情绪直述词 → 情绪类别。这是「告知」侧的词表。
_TELL_GROUPS: dict[str, tuple[str, ...]] = {
    "愤怒": ("生气", "愤怒", "恼火", "火大", "暴怒", "气愤"),
    "恐惧": ("害怕", "恐惧", "惊恐", "畏惧", "发怵"),
    "悲伤": ("悲伤", "难过", "伤心", "痛苦", "心碎", "沮丧"),
    "喜悦": ("高兴", "开心", "喜悦", "快乐", "兴奋"),
    "惊讶": ("惊讶", "吃惊", "震惊", "诧异"),
    "紧张": ("紧张", "不安", "忐忑", "焦虑"),
    "厌恶": ("厌恶", "恶心", "反感", "嫌弃"),
    "羞耻": ("羞愧", "羞耻", "尴尬", "难堪"),
    "疲惫": ("疲惫", "疲倦", "乏累"),
    "温柔": ("温柔", "心疼", "怜惜"),
}

#: 呈现信号 → 情绪类别。这是「展示」侧的词表：身体反应与可见动作。
#: 豁免判据就靠它 —— 邻域里出现同类信号，说明作者其实**展示了**。
_SHOW_SIGNALS: dict[str, tuple[str, ...]] = {
    "愤怒": ("攥紧", "青筋", "拍桌", "摔", "咬紧", "涨红", "瞪着", "拳头", "吼", "踢", "喘粗气"),
    "恐惧": ("发抖", "冷汗", "后退", "屏住呼吸", "瞳孔", "腿软", "攥住", "缩", "僵住"),
    "悲伤": ("眼泪", "喉头", "哽咽", "鼻子发酸", "垂着", "失神", "哭声"),
    "喜悦": ("嘴角", "笑了", "眼睛亮", "跳起来", "哼着", "脚步轻"),
    "惊讶": ("愣", "张着嘴", "瞳孔", "停住", "手一抖", "半晌"),
    "紧张": ("手心", "出汗", "咽口水", "来回踱", "指尖", "发抖"),
    "厌恶": ("皱眉", "别过脸", "后退", "捂住", "撇嘴"),
    "羞耻": ("脸红", "低下头", "耳根", "别开眼", "手足无措"),
    "疲惫": ("眼下", "打哈欠", "撑着", "眼皮", "拖着腿"),
    "温柔": ("放轻", "抚", "掖", "轻声", "笑了笑", "手心"),
}

_TELL_WORDS: dict[str, str] = {
    w: cat for cat, ws in _TELL_GROUPS.items() for w in ws
}
_TELL_RE = re.compile(
    r"(?:他|她|它|我|你|他们|她们|大家|心中|心里|心头)?"
    r"(?:感到|觉得|十分|非常|很|极其|格外|无比|有些|有点|越发|顿时|一时)?"
    r"(" + "|".join(sorted(_TELL_WORDS, key=len, reverse=True)) + r")"
)

#: 默认邻域半径（句）。
_SHOW_WINDOW_DEFAULT = 1
#: 同情绪未豁免直述达到多少处 → WARN。
_TELL_WARN_AT = 3


@dataclass
class TellHit:
    """一处情绪直述，以及它是否被邻域的呈现信号豁免。"""

    category: str
    tell: str
    sentence_index: int
    show_signal: str | None = None

    @property
    def exempt(self) -> bool:
        return self.show_signal is not None


@dataclass
class ShowTellReport:
    scene_id: str | None
    char_count: int
    window: int
    #: **全部**检出的直述（含被豁免的）。保留它，测试才能证明「不是漏检」。
    tells: list[TellHit] = field(default_factory=list)

    @property
    def violations(self) -> list[TellHit]:
        return [t for t in self.tells if not t.exempt]

    @property
    def exempted(self) -> list[TellHit]:
        return [t for t in self.tells if t.exempt]


def _find_show_signal(category: str, window_text: str) -> str | None:
    """在邻域文本里找该类情绪的呈现信号，返回第一个命中的。"""
    for sig in _SHOW_SIGNALS.get(category, ()):
        if sig in window_text:
            return sig
    return None


def scan_show_dont_tell(
    text: str,
    scene_id: str | None = None,
    window: int = _SHOW_WINDOW_DEFAULT,
) -> ShowTellReport:
    """检出情绪直述，并在邻域（同句 + 前后各 `window` 句）里找呈现信号。

    找到呈现信号的直述被标记为豁免（`show_signal` 非 None），
    **不产出 Finding**。只有「告知了、又没展示」才算违规。
    """
    if not text.strip():
        return ShowTellReport(scene_id, 0, window, [])

    sentences = _sentences(text)
    tells: list[TellHit] = []
    for i, sent in enumerate(sentences):
        for m in _TELL_RE.finditer(sent):
            word = m.group(1)
            category = _TELL_WORDS.get(word)
            if category is None:  # pragma: no cover - 交替正则保证可映射
                continue
            lo = max(0, i - window)
            hi = min(len(sentences), i + window + 1)
            neighbourhood = "".join(sentences[lo:hi])
            tells.append(
                TellHit(
                    category=category,
                    tell=word,
                    sentence_index=i,
                    show_signal=_find_show_signal(category, neighbourhood),
                )
            )
    return ShowTellReport(scene_id, len(text), window, tells)


def show_dont_tell_findings(report: ShowTellReport) -> list[Finding]:
    """只报**没有**被邻域呈现信号豁免的直述。同情绪聚合为一条。"""
    out: list[Finding] = []
    counts = Counter(t.category for t in report.violations)
    for category, n in sorted(counts.items()):
        hits = [t for t in report.violations if t.category == category]
        sev = Severity.WARN if n >= _TELL_WARN_AT else Severity.INFO
        if sev is Severity.WARN:
            message = (
                f"情绪直述「{category}」×{n}："
                f"前后 {report.window} 句内均无对应的呈现信号"
            )
        else:
            message = (
                f"情绪直述「{hits[0].tell}」（{category}）："
                f"前后 {report.window} 句内无对应的呈现信号"
            )
        out.append(
            Finding(
                code="craft:tell",
                severity=sev,
                scene_id=report.scene_id,
                message=message,
                suggestion=(
                    "用身体反应或动作替代："
                    + "、".join(_SHOW_SIGNALS.get(category, ())[:3])
                ),
                evidence={"category": category, "count": n},
            )
        )
    return out


# ===========================================================================
# 顶层：跑全部四个（签名与行为对齐 anti_slop.scan_ir）
# ===========================================================================


def scan_ir(ir) -> list[Finding]:
    """扫描整个 IR 的所有已写场景。跳过 `prose` 为空的场景。"""
    out: list[Finding] = []
    for s in ir.ordered_scenes():
        if not s.prose:
            continue
        out.extend(micro_tension_findings(scan_micro_tension(s.prose, scene_id=s.id)))
        out.extend(control_findings(scan_control(s.prose, scene_id=s.id)))
        out.extend(reality_findings(scan_reality(s.prose, scene_id=s.id)))
        out.extend(show_dont_tell_findings(scan_show_dont_tell(s.prose, scene_id=s.id)))
    return out


__all__ = [
    "ControlHit",
    "ControlReport",
    "MicroTensionReport",
    "ParagraphTension",
    "RealityReport",
    "ShowTellReport",
    "TellHit",
    "control_findings",
    "micro_tension_findings",
    "reality_findings",
    "scan_control",
    "scan_ir",
    "scan_micro_tension",
    "scan_reality",
    "scan_show_dont_tell",
    "show_dont_tell_findings",
]
