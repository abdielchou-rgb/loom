"""CSN 数值事实一致性 —— 纯规则、零依赖的跨场数值矛盾检测。

── 解决什么问题 ────────────────────────────────────────

跨章数值矛盾是读者最能一眼抓到的「吃书」形态：
第 3 章「他修了十一年」，第 40 章变成「十二年」。

这类矛盾**不需要任何语义理解**就能判定，因此是一致性门禁里性价比最高的一项。
前提是抽取足够保守 —— 抽取的最大风险不是漏，是**误报**：
把「青山局的编制有三百人」抽成「青山 = 300 人」，就会在正常文本上乱报警，
而一个会误报的门禁等于没有门禁（人会把它的输出全部忽略）。

所以本模块的取向是**误报治理优先**：宁可漏，不可错。

── 设计来源与许可证判断 ────────────────────────────────

工程模式学自 Æsirian 的 `core/csn_consistency.py`（Apache-2.0，其
`docs/attribution.md` 明确声明该模块为自研实现；InkOS 贡献的是门禁**思路**，
不是这个模块）。吸收的是三点**模式**：

  1. 数值事实表达为 `(subject, predicate, value, unit)` 四元组
  2. 抽取必须保守，误报抑制优先于召回
  3. 冲突判据是「同 subject + predicate + unit，值不同」

**词表与阈值独立推导，不照抄。** 数词规则来自汉语构词法（万以下：
数词 × 单位 逐段相加），单位表与守卫字符集按本项目的实际需求裁剪。
理由：许可证上「工程模式」可以借鉴，「内容/词表/阈值」不能 ——
这条界线是我在评估文档里给自己定的，得守住。

── 已知局限（写出来，不藏着）────────────────────────────

  * **召回受限**：谓语只取「剥掉体标记后的最后一个字」，所以
    「修炼了十一年」抽出的谓语是「炼」。两字动词会损失首字。
  * **改写不归一**：「在那座塔下守了十一年」与「守了十二年」的谓语都是「守」，
    能对上；但「修行了三十年」与「等了三十年」对不上 —— 纯规则做不到同义归一。
  * **代词主体不抽**：`他/她/它` 无法跨场稳定对齐，抽了只会制造噪声。
    代价是代词复述的矛盾检测不到。
  * **「的」修饰的短语不跟踪**：「沈砚的刀有三十斤重」被整体跳过。
    代价是「同一把刀在两章里重量不同」这类矛盾也检测不到 ——
    要覆盖它需要把「名字 + 的 + 名词」当作复合主体，那已经是浅层句法分析。
  * **主体归属靠就近原则**：「沈砚说陈默守了十一年」归给陈默（对），
    但如果句子结构更绕（「沈砚提到的那个陈默守了十一年」），
    就近原则未必对。纯规则的上限就在这里。

这些都是**有意为之的取舍**，不是待修的 bug。要突破它们需要语义理解，
那就不该塞进一个纯规则模块里假装做到了。

── 一次实战教训（值得留在代码里）────────────────────────

间隔上限 `_GAP_MAX` 最初取 6，单元测试用「在崖下等了」（5 字）全绿，
但真实行文是「在那座塔下守了」（7 字）—— **本模块最核心的用例被漏掉，
而测试全绿**。发现它的是拿真实段落跑一遍，不是测试套件。

教训有两条：
  1. 间隔类阈值的测试用例必须用**真实长度**的样本，用最短合法例子测等于没测。
  2. 单元测试全绿不等于功能可用 —— 还要拿真实输入跑一次。
     （这与 `scripts/verify.py` 的立场一致：验证口径本身也会骗人。）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 汉语数词
# ---------------------------------------------------------------------------

#: 数字字符（含「两」—— 汉语里「两百」比「二百」更常见）
_CN_DIGITS: dict[str, int] = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

#: 位值单位。万及以上不处理 —— 网文里「三万年」这类夸张数值本来就无意义，
#: 而且跨段位解析的出错面远大于收益。
_CN_UNITS: dict[str, int] = {"十": 10, "百": 100, "千": 1000}

_CN_NUM_CHARS = set(_CN_DIGITS) | set(_CN_UNITS)


def normalize_cn_number(text: str) -> int | None:
    """把中文数词归一化为 int。

    只接受**纯数词**（或阿拉伯数字）。带单位的（「十年」）返回 None ——
    单位由调用方负责剥离，这样「无法解析」与「解析出 0」不会混淆。

    算法是汉语构词法的直接翻译（万以下：数词 × 单位 逐段累加）：
        十一    → 十→10（省略前导「一」），一→1        = 11
        二十一  → 二→2，十→+20，一→+1                = 21
        一百零五→ 一→1，百→+100，零→0，五→+5          = 105
        两千三百→ 两→2，千→+2000，三→3，百→+300      = 2300
    """
    s = (text or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if any(ch not in _CN_NUM_CHARS for ch in s):
        return None

    section = 0
    number = 0
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        else:
            unit = _CN_UNITS[ch]
            # 「十」单独出现 = 10：汉语省略前导的「一」
            if number == 0:
                number = 1
            section += number * unit
            number = 0
    return section + number


# ---------------------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------------------

#: 受支持的计量单位。**刻意裁剪** —— 每个多收一个单位，就多一类误报。
#: 只保留网文里高频且歧义低的：年龄、时长、楼层、序号、人数、距离、重量、次数。
_UNITS = "年岁月天日夜里层楼号次个人斤把柄级品阶名步匹头只件座间"

#: 体标记（汉语语法封闭类）。剥离后才拿得到谓语词干。
_ASPECT = "了过着"

#: 第三人称代词（汉语语法封闭类）。出现在主体与数词之间时一并剥离。
_PRONOUNS = "他她它牠祂"

#: 机构后缀：名字后面紧跟这些字，说明它只是机构名的一部分，不是行为人。
#: 例：「青山局有三百人」——「青山」是机构名的一部分。
_INSTITUTION_SUFFIX = "局司部委厅署院校馆站队团会所厂矿队"

#: 地名后缀：同上，名字只是地名的一部分。
#: 例：「临阳城有三千人」——「临阳」是地名的一部分。
_PLACE_SUFFIX = "阳京州城港镇村区海山河江湖街路楼市省县国宫殿岛岭峰原野洲"

#: 主体与数词之间的最大间隔。
#:
#: 这个数被实战修正过一次：原先取 6，单元测试用「在崖下等了」（5 字）能过，
#: 但真实行文里是「在那座塔下守了」（7 字）—— **本模块的主用例被漏掉，
#: 而测试全绿**。教训：间隔上限的测试用例必须用真实长度的状语，
#: 用最短的合法例子测等于没测。
_GAP_MAX = 10


@dataclass(frozen=True)
class NumericFact:
    """一条数值事实：谁，做了什么，多少，什么单位。"""

    subject: str
    predicate: str
    value: int
    unit: str
    scene_id: str
    raw: str

    def render(self) -> str:
        return f"{self.subject}{self.predicate}了{self.value}{self.unit}"


@dataclass
class NumericConflict:
    """同一主体 + 同一谓语 + 同一单位，出现了不同的值。"""

    subject: str
    predicate: str
    unit: str
    facts: list[NumericFact] = field(default_factory=list)

    @property
    def values(self) -> list[int]:
        return sorted({f.value for f in self.facts})

    @property
    def scenes(self) -> list[str]:
        return sorted({f.scene_id for f in self.facts})

    def render(self) -> str:
        detail = "、".join(f"{f.value}{f.unit}（{f.scene_id}）" for f in self.facts)
        return f"{self.subject}{self.predicate}…：{detail}"


def _strip_edges(gap: str) -> str:
    """剥掉体标记与代词，返回谓语词干。"""
    s = gap
    for ch in _ASPECT + _PRONOUNS:
        s = s.replace(ch, "")
    return s.strip()


def scan_numeric_facts(
    text: str,
    *,
    names: set[str] | frozenset[str],
    scene_id: str = "",
) -> list[NumericFact]:
    """从一段文本里抽取数值事实。

    `names` 是**已登记的主体名**（角色名 + 别名）。只认具名主体：
    代词与未登记的名字一律不抽 —— 无法跨场对齐的主体抽出来只会制造噪声。
    """
    if not text or not names:
        return []

    # 长名优先，避免「慕容」吃掉「慕容城」的前缀
    alternation = "|".join(
        re.escape(n) for n in sorted(names, key=len, reverse=True) if n
    )
    if not alternation:
        return []

    pattern = re.compile(
        rf"(?P<subject>{alternation})"
        rf"(?P<gap>[^，。；！？、：\n\d]{{1,{_GAP_MAX}}}?)"
        rf"(?P<number>\d+|[零〇一二两三四五六七八九十百千]+)"
        rf"(?P<unit>[{_UNITS}])"
    )
    name_re = re.compile(alternation)

    out: list[NumericFact] = []
    # 手写扫描循环而不是 finditer：拒绝一个匹配时需要**从主体后一个字重扫**，
    # 好让间隔内侧那个名字有机会成为主体。
    # finditer 是非重叠的，直接 continue 会连同内侧的名字一起跳过。
    pos = 0
    while True:
        m = pattern.search(text, pos)
        if m is None:
            break
        subject = m.group("subject")
        nxt = text[m.end("subject") : m.end("subject") + 1]

        reject = False
        # 守卫 1：紧邻的「的」说明主体是修饰语，不是行为人
        #   「陈默的刀有三十斤重」—— 三十斤属于刀，不属于陈默
        if nxt == "的":
            reject = True
        # 守卫 2/3：机构名、地名的一部分
        elif nxt and (nxt in _INSTITUTION_SUFFIX or nxt in _PLACE_SUFFIX):
            reject = True
        # 守卫 4：间隔里出现另一个具名角色 → 动作属于那个人
        #   「沈砚说陈默守了十一年」：主体是陈默，不是句首的沈砚
        elif name_re.search(m.group("gap")):
            reject = True

        if reject:
            # 从主体后一个字重扫，而不是跳过整个匹配
            pos = m.start("subject") + 1
            continue

        value = normalize_cn_number(m.group("number"))
        predicate = _strip_edges(m.group("gap"))
        if value is None or not predicate:
            pos = m.start("subject") + 1
            continue

        # 谓语只取最后一个字（汉语里动词紧邻其补语）。
        # 这是有意的取舍：两字动词会损失首字，但能稳定剥掉
        # 「在那座塔下守了」这类状语，见模块 docstring 的局限说明。
        out.append(
            NumericFact(
                subject=subject,
                predicate=predicate[-1],
                value=value,
                unit=m.group("unit"),
                scene_id=scene_id,
                raw=m.group(0),
            )
        )
        pos = m.end()
    return out


def find_conflicts(facts: list[NumericFact]) -> list[NumericConflict]:
    """找出「同主体 + 同谓语 + 同单位，值不同」的事实组。

    同值复述不算矛盾（角色反复说同一件事是正常的）。
    """
    groups: dict[tuple[str, str, str], list[NumericFact]] = {}
    for f in facts:
        groups.setdefault((f.subject, f.predicate, f.unit), []).append(f)

    out: list[NumericConflict] = []
    for (subject, predicate, unit), members in sorted(groups.items()):
        if len({m.value for m in members}) > 1:
            out.append(
                NumericConflict(
                    subject=subject,
                    predicate=predicate,
                    unit=unit,
                    facts=members,
                )
            )
    return out


__all__ = [
    "NumericConflict",
    "NumericFact",
    "find_conflicts",
    "normalize_cn_number",
    "scan_numeric_facts",
]
