"""DRESS 风格漂移三维检测 —— 纯规则、零依赖的风格漂移门禁。

── 解决什么问题 ────────────────────────────────────────

Loom 目前只用「提示词版本 + `model_id` 溯源」保证风格一致。那记录的是
文本**怎么产生的**（provenance），不是风格**是否真的漂移了**（measurement）。
于是「换了模型但风格没变」是一句没有证据的宣称 —— 它无法被证伪。

本模块把它变成一个**可测量**的问题：

    overall_authenticity = style_fidelity × content_independence × fluency
    passed = overall_authenticity >= 1 - threshold        # 默认 threshold = 0.15

── 为什么 content_independence 才是关键那一维 ────────────

三维里另外两维都容易被「自证」。风格保真度尤其危险：
**只有当内容也变了，保真度才有信息量。**

若第 2 章讲的还是第 1 章那些事，「听起来一样」是理所当然的 ——
这时的高 fidelity 什么都没证明，它被内容解释掉了。

所以 `content_independence` 衡量的是「内容明明不同，风格相似性却依然成立」：

    同一内容对     → 独立性低（相似性可由内容解释）
    异内容同风格对 → 独立性高（相似性无法由内容解释）

这个**非对称**是本模块的全部价值。它被 `tests/test_dress.py` 第 4 组用
同一对文本钉死：两对的 `style_fidelity` 逐位相同，唯一差异是
`content_independence`。一个对两种情况返回同一个值的实现是失败的，
哪怕其余测试全绿 —— 那正是「看着很好、其实什么都没测」的指标。

── 设计来源与许可证判断 ────────────────────────────────

本模块**没有**照抄任何第三方实现，只从下列公开方法论推导：

  function-word 风格指纹   Mosteller & Wallace《Inference and Disputed
                          Authorship: The Federalist》(1964)。功能词（虚词）
                          的频率是作者风格最稳的指纹 —— 因为作者**无法自觉
                          控制**虚词的使用。本模块的 `particle_ratio` 即此。

  Delta / 风格距离          Burrows, "Delta: a Measure of Stylistic Difference
                          and a Guide to Authorship Attribution",
                          Literary and Linguistic Computing 17(3), 2002。
                          以特征向量的**相对差异**度量风格距离（本模块的
                          `style_fidelity` 用逐维比值相似度取平均）。

  离群鲁棒性                Leys et al., "Detecting outliers: Do not use
                          standard deviation around the mean, use absolute
                          deviation around the median", J. Exp. Soc. Psychol.
                          49(4), 2013。中位数对离群点稳健，均值不稳健 ——
                          这是一章动作戏/闪回不该拖走风格基线的理由。

**词表与阈值独立推导，不照抄。** 「工程模式」可以借鉴，「内容/词表/阈值」
不能 —— 这条界线与本项目 `craft.py` / `csn.py` 的立场一致。

── 为什么不抄那个死掉的参考实现（反面教材）────────────────

源项目有一个 2028 行的 `fingerprint.py`，其 `NarrativeFingerprint` 声明了
5 个网文相关字段，但**全项目没有任何地方给它们赋值，永远是 0.0**；
它还在 `except Exception: pass` 里 import 两个**并不存在的模块**。

这是教科书式的静默失败：一个看起来覆盖了 5 个维度、实际上一个都没测的
指标，比没有这个指标更糟 —— 它会让人以为「已经测过了」。

所以本模块**只借 DRESS 的公式与中位数基线这两点**，风格特征从第一性原理
自己写，且每条特征都有可复算的定义（见 `StyleProfile`）。**不使用 LLM，
不使用向量嵌入** —— 特征全部是句长分布、虚词占比、对话占比、标点节奏，
确定性、可解释、可逐条复核。

── 已知局限（写出来，不藏着）────────────────────────────

  * **无分词、无句法**：所有特征都是字符级计数。虚词占比按**字符**算，
    不按词算 —— 「的」在复合词里也会被计入。这是零依赖下的取舍。
  * **内容独立性用字符二元组近似**：`content_independence` 以内容字符流的
    二元组 Jaccard 距离作为「内容差异」的代理。同义改写（换了词但意思一样）
    会被判为「内容不同」，独立性偏高 —— 纯规则做不到同义归一。
  * **阈值是产品决策**：0.15 只是一个保守默认值。它应当由作者按实际
    稿件的风格方差调整，而不是当成物理常数。
  * **基线的章数下限**：少于 2 章时无法建立「跨章」基线，`scan_ir` 直接
    返回空（不报警）。**空返回 ≠ 通过** —— 调用方应当把「章数不足」单独
    记为 SKIPPED，而不是当作绿色。（与 `validators/base.py` 的
    「SKIPPED ≠ PASS」原则一致。）
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, fields

from ..ir.enums import Severity
from ..validators.base import Finding

# ---------------------------------------------------------------------------
# 切分与词表（全部为汉语语法封闭类 / 字符集，无外部词表）
# ---------------------------------------------------------------------------

#: 切句。只按终结标点与换行切 —— 逗号不切，因为逗号是**句内**节奏信号。
_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")

#: 虚词（功能词）字符集。出处：Mosteller & Wallace 的功能词指纹思想。
#: 这些是汉语里作者最不自觉使用的封闭类，因此最能代表「手感」。
_PARTICLES: frozenset[str] = frozenset(
    "的了着吗呢吧啊呀嘛哦嗯么地得之乎者也"
)

#: 对话标记（成对与单侧都算）。用于 dialogue_ratio。
_DIALOGUE_MARKS: tuple[str, ...] = ("「", "」", "『", "』", "“", "”", "\"", "'")

#: 标点与空白 —— 计算内容字符流时剥离。
_PUNCT: frozenset[str] = frozenset(
    "。！？!?；;，,、：:「」『』“”\"'（）()《》〈〉…—－-·~～ \t\r\n"
)

#: 流畅度：超过这个字数的句子算「流水句」，按比例惩罚。
_LONG_SENTENCE_LEN = 40
#: 流畅度：短于这个字数的句子算「碎片」，按比例惩罚。
_MIN_SENTENCE_LEN = 2

#: 风格特征向量的维度顺序（`baseline` 与 `style_fidelity` 共用）。
_FEATURES: tuple[str, ...] = (
    "mean_sentence_len",
    "sentence_len_cv",
    "dialogue_ratio",
    "particle_ratio",
    "comma_per_sentence",
    "terminal_ratio",
)

#: 默认阈值。`passed = overall >= 1 - threshold`。
DEFAULT_THRESHOLD = 0.15


def _sentences(text: str) -> list[str]:
    """切句。按终结标点与换行切，逗号不切。"""
    return [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]


def _content_stream(text: str) -> str:
    """内容字符流：剥离标点、空白与虚词。

    剥离虚词是有意的 —— 虚词属于**风格**（见 `_PARTICLES`），
    把它们留在「内容」里会让两段毫无内容关联的文本因虚词雷同而显得
    「内容相近」。剥掉之后剩下的才是内容代理。
    """
    return "".join(ch for ch in text if ch not in _PUNCT and ch not in _PARTICLES)


def _bigrams(stream: str) -> set[str]:
    """字符二元组集合。用于内容重叠度。"""
    return {stream[i : i + 2] for i in range(len(stream) - 1)}


# ---------------------------------------------------------------------------
# 风格档案
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StyleProfile:
    """一章（或一场）的可测量风格特征。

    六个维度全部是非负标量，全部可逐条复算：

      mean_sentence_len    句长均值（字）—— 节奏的粗粒度
      sentence_len_cv      句长变异系数 = 标准差 / 均值 —— 节奏的起伏度
      dialogue_ratio       含对话标记的句子占比 —— 叙述/对白配比
      particle_ratio       虚词字符数 / 总字符数 —— 功能词指纹
      comma_per_sentence   每句逗号数 —— 句内停顿节奏
      terminal_ratio       每句叹/问号数 —— 语气强度

    选择这些而不是「词频向量」，是为了让每个数字都能被人一眼看懂、
    并指着文本说「对，就是这个」。
    """

    mean_sentence_len: float = 0.0
    sentence_len_cv: float = 0.0
    dialogue_ratio: float = 0.0
    particle_ratio: float = 0.0
    comma_per_sentence: float = 0.0
    terminal_ratio: float = 0.0

    def vector(self) -> tuple[float, ...]:
        """按 `_FEATURES` 顺序返回特征向量。"""
        return tuple(getattr(self, f) for f in _FEATURES)


def profile(text: str) -> StyleProfile:
    """把一段文本压成风格档案。空文本 → 全零档案（不抛错）。"""
    sents = _sentences(text)
    if not sents:
        return StyleProfile()

    lens = [len(s) for s in sents]
    mean_len = statistics.fmean(lens)
    cv = (statistics.pstdev(lens) / mean_len) if mean_len else 0.0

    n = len(sents)
    dialogue = sum(
        1 for s in sents if any(m in s for m in _DIALOGUE_MARKS)
    ) / n

    body = "".join(sents)
    total = len(body)
    particles = sum(1 for ch in body if ch in _PARTICLES)
    particle_ratio = (particles / total) if total else 0.0

    commas = body.count("，") + body.count(",")
    comma_per_sentence = commas / n

    terminal = (
        text.count("！") + text.count("!") + text.count("？") + text.count("?")
    ) / n

    return StyleProfile(
        mean_sentence_len=mean_len,
        sentence_len_cv=cv,
        dialogue_ratio=dialogue,
        particle_ratio=particle_ratio,
        comma_per_sentence=comma_per_sentence,
        terminal_ratio=terminal,
    )


# ---------------------------------------------------------------------------
# 基线：剔除 2σ 离群后的中位数
# ---------------------------------------------------------------------------


def _trim_2sigma(values: list[float]) -> list[float]:
    """剔除落在 [mean-2σ, mean+2σ] 之外的值。

    全被剔除时回退为原列表（宁可留噪声，也不要空集导致下游炸除零）。
    σ 用总体标准差（`pstdev`）：这里的「总体」就是这份稿件的全部章节，
    不是从中抽样，故无需样本修正。
    """
    if len(values) < 3:
        return list(values)
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values)
    if sd == 0:
        return list(values)
    lo, hi = mean - 2.0 * sd, mean + 2.0 * sd
    kept = [v for v in values if lo <= v <= hi]
    return kept or list(values)


def baseline(profiles: list[StyleProfile]) -> StyleProfile:
    """多章风格基线：**逐维**剔除 2σ 离群后取中位数。

    为什么是中位数而不是均值（Leys et al. 2013）：一章动作戏或闪回会让
    句长分布极端偏离。均值被它拖走，中位数不会。剔除 2σ 离群是第二道保险，
    让**同时**出现的两个中度离群也不至于左右基线。

    空列表 → 全零档案；单章 → 就是它自己（无从聚合）。
    """
    if not profiles:
        return StyleProfile()
    if len(profiles) == 1:
        return profiles[0]

    aggregated: dict[str, float] = {}
    for f in _FEATURES:
        values = [getattr(p, f) for p in profiles]
        aggregated[f] = float(statistics.median(_trim_2sigma(values)))
    return StyleProfile(**aggregated)


# ---------------------------------------------------------------------------
# 三维
# ---------------------------------------------------------------------------


def style_fidelity(p: StyleProfile, base: StyleProfile) -> float:
    """风格保真度 ∈ [0, 1]：逐维比值相似度取平均。

    单维相似度 = min(a, b) / max(a, b)（两值皆为 0 时记为 1.0）。
    这是对称、有界、无参数的相似度 —— 与 Burrows Delta 的「相对差异」
    同源，但不需要 z-score 标准化（本模块不假设正态）。

    注意：保真度高**不代表**风格没漂移 —— 若内容没变，高保真度毫无信息量。
    这正是 `content_independence` 存在的原因。
    """
    sims: list[float] = []
    for f in _FEATURES:
        a, b = getattr(p, f), getattr(base, f)
        hi, lo = max(a, b), min(a, b)
        sims.append(1.0 if hi == 0 else lo / hi)
    return sum(sims) / len(sims)


def content_independence(text: str, base_text: str) -> float:
    """内容独立性 ∈ [0, 1]：风格相似性**不被内容重合解释**的程度。

    定义：1 - 内容重叠度，内容重叠度 = 两段内容字符流二元组的 Jaccard。

        同一内容对     → 重叠 1 → 独立性 0（相似性完全由内容解释）
        异内容同风格对 → 重叠 0 → 独立性 1（相似性无法由内容解释）

    任一侧内容流为空（无法比较）时返回 1.0：没有可被内容解释的相似性。

    这是本模块最要紧的一维。它让「换了模型但风格没变」这句话必须回答
    一个更难的问题：**内容变了没有？** 若内容没变，乘积归零，
    `passed` 必然为假。
    """
    a = _bigrams(_content_stream(text))
    b = _bigrams(_content_stream(base_text))
    if not a or not b:
        return 1.0
    overlap = len(a & b) / len(a | b)
    return 1.0 - overlap


def fluency(text: str) -> float:
    """流畅度 ∈ [0, 1]：对退化文本的惩罚。

    三项惩罚（加权）：
      重复句比例 × 0.5   整段复读是最典型的生成退化
      流水句比例 × 0.3   超长句（> 40 字）说明句读失控
      碎片句比例 × 0.2   过短句（< 2 字）说明切分破碎

    空文本 → 0.0（没有可读性可言，不是「完美流畅」）。
    """
    sents = _sentences(text)
    if not sents:
        return 0.0
    n = len(sents)
    duplicate = 1.0 - len(set(sents)) / n
    long_run = sum(1 for s in sents if len(s) > _LONG_SENTENCE_LEN) / n
    fragment = sum(1 for s in sents if len(s) < _MIN_SENTENCE_LEN) / n
    penalty = 0.5 * duplicate + 0.3 * long_run + 0.2 * fragment
    return max(0.0, 1.0 - penalty)


# ---------------------------------------------------------------------------
# 三维汇总
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthenticityReport:
    """一章的三维体检。

    `overall` 与 `passed` 都是**属性**而不是存储字段 —— 这样任何一份
    报告都不可能持有与公式不一致的结论（防止「构造出来的对象自己骗自己」）。
    """

    style_fidelity: float
    content_independence: float
    fluency: float
    threshold: float = DEFAULT_THRESHOLD

    @property
    def overall(self) -> float:
        """overall_authenticity = 三维乘积。任一项为 0 则整体为 0。"""
        return self.style_fidelity * self.content_independence * self.fluency

    @property
    def overall_authenticity(self) -> float:
        """`overall` 的全名（对齐 DRESS 公式的记法）。"""
        return self.overall

    @property
    def passed(self) -> bool:
        """边界是「≥」：`overall >= 1 - threshold`。"""
        return self.overall >= 1.0 - self.threshold

    def render(self) -> str:
        mark = "✓" if self.passed else "✗"
        return (
            f"{mark} 真实度 {self.overall:.3f} "
            f"= 保真 {self.style_fidelity:.3f}"
            f" × 内容独立 {self.content_independence:.3f}"
            f" × 流畅 {self.fluency:.3f}"
        )


def authenticity(
    text: str,
    base_text: str,
    base: StyleProfile,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> AuthenticityReport:
    """把一章与基线、参考正文比较，产出三维报告。

    参数：
      text       待检章正文
      base_text  参考正文（通常是**其余**章节拼接），用于内容独立性
      base       风格基线（`baseline(...)` 的产物）
    """
    return AuthenticityReport(
        style_fidelity=style_fidelity(profile(text), base),
        content_independence=content_independence(text, base_text),
        fluency=fluency(text),
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# 顶层：跨章门禁
# ---------------------------------------------------------------------------


def scan_ir(ir, *, threshold: float = DEFAULT_THRESHOLD) -> list[Finding]:
    """扫描整个 IR：找出与跨章风格基线不符的章节。

    流程：
      1. 收集所有有 `prose` 的场景
      2. 少于 2 章 → 无法建立跨章基线，返回空（**空 ≠ 通过**，见模块 docstring）
      3. 用 `baseline` 建立风格基线
      4. 逐章：以「其余章拼接」为参考正文，跑三维体检
      5. 未通过者产出一条 WARN Finding

    严重度取 WARN 而非 ERROR：风格漂移是**品味/一致性**信号，不是结构性
    错误（与本项目 `craft.py` 的严重度政策一致）。真正的结构门禁在
    `loom/validators/` 里。
    """
    scenes = [s for s in ir.ordered_scenes() if s.prose]
    if len(scenes) < 2:
        return []

    profiles = [profile(s.prose) for s in scenes]
    base = baseline(profiles)

    out: list[Finding] = []
    for i, s in enumerate(scenes):
        others = "".join(o.prose for j, o in enumerate(scenes) if j != i)
        report = authenticity(s.prose, others, base, threshold=threshold)
        if report.passed:
            continue
        out.append(
            Finding(
                code="audit:style_drift",
                severity=Severity.WARN,
                scene_id=s.id,
                message=(
                    f"风格漂移：真实度 {report.overall:.3f} < {1 - threshold:.3f}"
                    f"（保真 {report.style_fidelity:.3f}"
                    f" × 内容独立 {report.content_independence:.3f}"
                    f" × 流畅 {report.fluency:.3f}）"
                ),
                suggestion=(
                    "逐维排查：保真低 → 句式/虚词/标点节奏偏离基线；"
                    "内容独立低 → 本章与其余章内容高度重合，"
                    "高保真度没有信息量；流畅低 → 复读或流水句"
                ),
                evidence={
                    "style_fidelity": round(report.style_fidelity, 4),
                    "content_independence": round(report.content_independence, 4),
                    "fluency": round(report.fluency, 4),
                    "overall": round(report.overall, 4),
                    "threshold": threshold,
                },
            )
        )
    return out


# 让静态检查工具知道 `fields` 被用于自检（见 `_self_check`）。
def _self_check() -> None:
    """开发期自检：`_FEATURES` 必须与 `StyleProfile` 的字段完全一致。

    防的是「加了字段却忘了加进 `_FEATURES`」—— 那样该维度会静默地
    不参与基线与保真度计算，正是本模块要消灭的那类静默失败。
    """
    declared = {f.name for f in fields(StyleProfile)}
    assert declared == set(_FEATURES), (
        f"_FEATURES 与 StyleProfile 字段不一致：{declared ^ set(_FEATURES)}"
    )


_self_check()


__all__ = [
    "DEFAULT_THRESHOLD",
    "AuthenticityReport",
    "StyleProfile",
    "authenticity",
    "baseline",
    "content_independence",
    "fluency",
    "profile",
    "scan_ir",
    "style_fidelity",
]
