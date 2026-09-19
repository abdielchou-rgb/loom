"""媒介写作形态规格（medium craft）。

**为什么放在 IR 层，而不是提示词层**

跟 ``ir/arcs.py`` 是同一个理由：媒介的写作形态是**叙事事实**，不是某个
提示词的实现细节。它有三个消费方，层次不能倒：

    ir/medium_craft.py              唯一定义（本文件）
      ├─ llm/prompts.py               告诉模型「这个媒介该写成什么样」
      ├─ llm/mock.py                  桩件按媒介产出**形态正确**的离线正文
      └─ render/*                     渲染器解析产出的形态（剧本要有对白行可提取）

放在提示词层会让桩件与渲染器反向依赖 LLM 层 —— 而桩件是「无 key 也能跑」的
基线，它绝不能依赖一个可选依赖。

**这个模块的直接由头**

``prose`` 提示词原本写死「你是小说作者」。结果是：选了「剧本」，产出的仍然
是小说散文，只是被 ``render_fountain`` 套了一层场景标题 —— 用户看到的是
「排版成剧本的小说」。形态规格缺失，是结果不像剧本的**根因**，
而排版不是补救手段。

**关于方法论来源**

- 剧本 / 微短剧：主场景剧本格式（master scene script）+ Fountain 规范
  （fountain.io）。动作线 / 人物提示行 / 对白 / 括号提示 / 转场是格式事实，
  不是本项目发明的启发式。
- 漫画：Scott McCloud《理解漫画》第六章的六种画格转场
  （moment-to-moment / action-to-action / subject-to-subject /
  scene-to-scene / aspect-to-aspect / non-sequitur）。
- 网文 / 微短剧的「追读」与「付费卡点」：这是**本项目的产品定义**
  （见 ``Medium.WEB_NOVEL`` / ``Medium.MICRO_DRAMA`` 的注释与
  ``SceneNode.is_paywall_gate`` 字段），不假托外部权威。
- 长度换算（页 / 秒 / 格）是**行业常用粗估**，用于给模型一个量级感，
  不是精确计量。不要在别处把它当真值用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import Medium


@dataclass(frozen=True)
class MediumCraft:
    """一个媒介的写作形态规格。

    role         写作者角色（进提示词的身份设定）
    form         形态硬约束。模型必须遵守，且这些约束**可被渲染器解析**
    bans         该媒介特有的禁止项（通用文风禁令在 prose 提示词里，不重复）
    sample       一个正确的短样例。**没有样例的格式说明，模型只会照着印象写**
    unit         长度单位（字 / 页 / 分钟 / 秒 / 格 / 幕）
    words_per_unit  1 个单位折合多少字（行业粗估，仅用于换算长度提示）
    """

    medium: Medium
    label: str
    role: str
    form: str
    bans: str
    sample: str
    unit: str
    words_per_unit: int = 1


#: 通用禁令写在 prose 提示词的 system 段（视角纪律 / 反 slop / 节奏），
#: 这里只写**该媒介独有**的。重复写一遍会让提示词变长而约束不变。
MEDIUM_CRAFT: dict[Medium, MediumCraft] = {
    Medium.NOVEL: MediumCraft(
        medium=Medium.NOVEL,
        label="小说",
        role="小说作者",
        form=(
            "- 散文体叙事，段落推进；可以进入聚焦人物的意识。\n"
            "- 叙述与对白按场景需要配比，无固定格式。\n"
            "- 一行一个段落起落，不要整段不分行。"
        ),
        bans="无额外禁止项（通用文风禁令已列出）。",
        sample=(
            "他把包袱放在门槛上，没有立刻推门。\n"
            "屋里有人在说话，声音很低，低到听不清字，只听得见停顿。"
        ),
        unit="字",
        words_per_unit=1,
    ),
    Medium.WEB_NOVEL: MediumCraft(
        medium=Medium.WEB_NOVEL,
        label="网文",
        role="网文作者",
        form=(
            "- 章节体。每段 1-3 句，单段不超过 4 行 —— 竖屏阅读，长段落等于劝退。\n"
            "- 对白驱动推进，用对白代替叙述交代信息。\n"
            "- 章末必须有钩子：一个未答之问、一个反转、或一个刚露头的威胁。\n"
            "- 章节开头直接进入冲突，不要环境描写开场。"
        ),
        bans=(
            "- 禁止用大段环境/身世描写开场。\n"
            "- 禁止章末收束成完整句号（那等于告诉读者「可以明天再看」）。\n"
            "- 禁止单段超过 4 行。"
        ),
        sample=(
            "「你昨夜去哪了？」\n"
            "她没抬头，手指在碗沿上停了一下。\n"
            "「出门。」\n"
            "「出门？」他把刀放在桌上，「门闩是从外面插的。」"
        ),
        unit="字",
        words_per_unit=1,
    ),
    Medium.SCREENPLAY: MediumCraft(
        medium=Medium.SCREENPLAY,
        label="剧本",
        role="编剧",
        form=(
            "- 主场景剧本格式：动作线 + 人物提示行 + 对白。\n"
            "- **动作线**：现在时，只写摄影机能拍到、麦克风能录到的东西。\n"
            "- **人物提示行**：角色名单独一行，中文居中对齐即可，后接对白。\n"
            "- **括号提示**：写在人物名后的括号里，如「（低声）」，"
            "只用于演员必须知道的语气或动作，能省则省。\n"
            "- **转场**：需要时写 `CUT TO:`。\n"
            "- **不要写场景标题** —— 场景标题由系统按地点与时间生成，"
            "你写了会重复。\n"
            "- **不要写镜头**（除非剧情必需）：导演会决定怎么拍。"
        ),
        bans=(
            "- 禁止心理描写与「他感到…」「她意识到…」—— 不可拍摄。\n"
            "- 禁止比喻与作者的评论。\n"
            "- 禁止用对白复述观众已经看到的事。"
        ),
        sample=(
            "门被推开一半，停住。\n"
            "他的手还按在门框上，指节发白。\n\n"
            "陈默\n"
            "（低声）\n"
            "你昨夜去哪了。\n\n"
            "她没有抬头。\n\n"
            "阿枝\n"
            "出门。\n\n"
            "陈默把刀放在桌上。木桌裂了一道缝，刀正好压在缝上。\n\n"
            "陈默\n"
            "门闩是从外面插的。\n\n"
            "CUT TO:"
        ),
        unit="页",
        words_per_unit=180,
    ),
    Medium.MICRO_DRAMA: MediumCraft(
        medium=Medium.MICRO_DRAMA,
        label="微短剧",
        role="短剧编剧",
        form=(
            "- 与剧本同格式（动作线 + 人物 + 对白），但节拍更硬：\n"
            "- 单场 30-90 秒。\n"
            "- 开场 3 秒内必须出现冲突或反转，不许铺垫。\n"
            "- 卡点前一场必须留下最强的未解悬念。\n"
            "- 对白要**只靠听就能懂**：竖屏小屏，观众常常在看别处。\n"
            "- 每场只推进一件事，不要并行两条信息线。"
        ),
        bans=(
            "- 禁止超过 3 行的动作线。\n"
            "- 禁止单场出现超过 3 个角色（小屏认不住脸）。\n"
            "- 禁止需要看画面细节才懂的对白。"
        ),
        sample=(
            "一记耳光。她的头偏过去，耳环掉在地上。\n\n"
            "林晚\n"
            "这一巴掌，我记下了。\n\n"
            "她转身就走。身后传来玻璃碎裂的声音。\n\n"
            "林晚（画外）\n"
            "三年后，我会让你跪着捡起来。\n\n"
            "CUT TO:"
        ),
        unit="秒",
        words_per_unit=4,
    ),
    Medium.INTERACTIVE_FICTION: MediumCraft(
        medium=Medium.INTERACTIVE_FICTION,
        label="互动小说",
        role="互动叙事设计师",
        form=(
            "- 正文之后给出选项，每行一个，格式为 `* 选项文字`。\n"
            "- 选项必须是**行动**（「推门」「把刀收起来」），不是情绪"
            "（「感到害怕」）。\n"
            "- 2-4 个选项，且每个选项都要有**可观察的后果** —— "
            "后果就是 IR 里的状态增量。\n"
            "- 选项之间要有真实取舍：选了一个，就要放弃另一个的好处。"
        ),
        bans=(
            "- 禁止假选择（只有一个选项合理，其余明显送死）。\n"
            "- 禁止选项之后没有后果（选了等于没选）。\n"
            "- 禁止选项里写结果（「推门（会看到尸体）」）。"
        ),
        sample=(
            "门虚掩着，里面没有光。\n"
            "你的手停在门板上。\n\n"
            "* 推门进去\n"
            "* 先绕到窗边看一眼\n"
            "* 收回手，转身下楼"
        ),
        unit="字",
        words_per_unit=1,
    ),
    Medium.VISUAL_NOVEL: MediumCraft(
        medium=Medium.VISUAL_NOVEL,
        label="视觉小说",
        role="视觉小说编剧",
        form=(
            "- 一行一条语句：`角色名「对白」`，或 `场景描述`，或 `旁白`。\n"
            "- 对白短（1-2 句），可随时推进；不要写大段独白。\n"
            "- 需要立绘/背景变化时，单独一行写 `【背景：…】` / "
            "`【立绘：角色名-表情】`。\n"
            "- 旁白单独成行，不混进对白。"
        ),
        bans=(
            "- 禁止把心理独白写成对白念出来。\n"
            "- 禁止单条对白超过 3 句。\n"
            "- 禁止在同一行里混写场景与对白。"
        ),
        sample=(
            "【背景：客栈大堂 - 夜】\n"
            "【立绘：阿枝-平静】\n"
            "阿枝「你昨夜去哪了。」\n"
            "陈默「出门。」\n"
            "【立绘：陈默-冷】\n"
            "陈默「门闩是从外面插的。」\n"
            "旁白：木桌裂了一道缝，刀正好压在缝上。"
        ),
        unit="字",
        words_per_unit=1,
    ),
    Medium.COMIC: MediumCraft(
        medium=Medium.COMIC,
        label="漫画",
        role="漫画分镜编剧",
        form=(
            "- 按画格写：每格一段，格式为 `格 N｜画面：…｜对白：…｜音效：…`。\n"
            "- **画面**只写这一格里**静止可见**的东西 —— 一格装不下一个动作，"
            "一个动作要拆成两格。\n"
            "- 写明画格之间的**转场类型**（McCloud 六种）：\n"
            "  动作到动作 / 瞬间到瞬间 / 主体到主体 / 场景到场景 /\n"
            "  视角到视角 / 无关联。\n"
            "- 对白与音效字要短，气泡里放不下长句。"
        ),
        bans=(
            "- 禁止一格塞进一个完整动作（应拆格）。\n"
            "- 禁止用文字描述画面已经表达的东西。\n"
            "- 禁止超过 3 个气泡的画格。"
        ),
        sample=(
            "格 1｜画面：门被推开一半，一只手按在门框上，指节发白。\n"
            "     ｜转场：场景到场景\n\n"
            "格 2｜画面：陈默的脸，半明半暗。\n"
            "     ｜对白：你昨夜去哪了。\n"
            "     ｜转场：主体到主体\n\n"
            "格 3｜画面：桌面的特写，一把刀压在裂缝上。\n"
            "     ｜音效：嗒。\n"
            "     ｜转场：视角到视角"
        ),
        unit="格",
        words_per_unit=25,
    ),
    Medium.MURDER_MYSTERY: MediumCraft(
        medium=Medium.MURDER_MYSTERY,
        label="剧本杀",
        role="剧本杀设计师",
        form=(
            "- 按幕组织，每幕包含四部分：\n"
            "  1. 【公开信息】所有玩家在这一幕都能读到的内容\n"
            "  2. 【私人线索】只有本角色知道的信息\n"
            "  3. 【本幕任务】搜证 / 讨论 / 指认，明确写清要做什么\n"
            "  4. 【可问问题】这一幕玩家之间必然会问到的 2-3 个问题\n"
            "- 线索要能被**多方解释**：同一条线索至少支持两种推断。"
        ),
        bans=(
            "- 禁止把只有主持人知道的真相写进玩家本。\n"
            "- 禁止线索指向唯一解（应保留 2-3 个可辩护的嫌疑人）。\n"
            "- 禁止任务写成「找出凶手」这种无步骤的笼统目标。"
        ),
        sample=(
            "【第一幕 · 公开信息】\n"
            "子时，客栈大门从外面被闩上。所有人都在堂内。\n\n"
            "【私人线索 · 陈默】\n"
            "你昨夜出门时，看见阿枝的房门开着，里面没有灯。\n\n"
            "【本幕任务】\n"
            "搜证：客栈内可搜 3 处。讨论：各自说明子时所在。\n\n"
            "【可问问题】\n"
            "- 门闩是谁插的？\n"
            "- 阿枝房里的灯为什么灭了？"
        ),
        unit="幕",
        words_per_unit=400,
    ),
}


#: 场景地点里自带的内外景标记。约定：结构层输出的 `location` 写成
#: 「内景·书房」这种带标记的形式。
#:
#: **为什么用约定而不是给 SceneNode 加字段**：内外景是剧本才关心的属性，
#: 为一个媒介往中性场景节点上加字段，会让 IR 的字段表被单一媒介拖着长。
#: 而把它塞进地点串里，代价只是一条**解析约定** —— 约定必须有唯一实现，
#: 所以解析函数放在这里，渲染器与校验器都来取，不许各写一份。
_SLUG_MARK = re.compile(
    r"^\s*(内景|外景|内外景|内/外景|INT\.?|EXT\.?|I/E\.?)\s*"
    r"[.·．、:：\-—\s]*(.*)$",
    re.IGNORECASE,
)

_INT_EXT_ZH = {
    "内景": "内景", "内": "内景", "int": "内景",
    "外景": "外景", "外": "外景", "ext": "外景",
}


def split_slugline(loc: str | None) -> tuple[str, str]:
    """把场景地点串拆成（内外景标记, 地点名）。

    标记取不到时返回空串 —— 由调用方决定怎么显示（渲染器标成「内/外景」，
    校验器只拿地点名去查别名索引）。**不猜**：没有标记就是没有标记。

    >>> split_slugline("内景·书房")
    ('内景', '书房')
    >>> split_slugline("INT. STUDY")
    ('内景', 'STUDY')
    >>> split_slugline("书房")
    ('', '书房')
    >>> split_slugline("内外景·书房")
    ('内/外景', '书房')
    """
    m = _SLUG_MARK.match(loc or "")
    if not m:
        return "", (loc or "").strip()
    mark, place = m.group(1).strip(), m.group(2).strip()
    key = mark.replace(".", "").lower()
    if key in _INT_EXT_ZH:
        return _INT_EXT_ZH[key], place
    # 「内外景」「I/E」= 作者还没定。原样标成未定，不替他猜。
    return "内/外景", place


def craft_for(medium: Medium | str | None) -> MediumCraft:
    """取媒介的写作形态规格。未知或缺失一律退化为小说 —— 不抛。

    为什么不抛：媒介来自用户输入，一个拼错的媒介值不该让整条流水线挂掉。
    但退化必须是**可观测**的 —— 调用方要把 `label` 写进提示词，
    所以退化会出现在提示词里而不是沉默发生。
    """
    if medium is None:
        return MEDIUM_CRAFT[Medium.NOVEL]
    try:
        m = medium if isinstance(medium, Medium) else Medium(str(medium))
    except (ValueError, TypeError):
        return MEDIUM_CRAFT[Medium.NOVEL]
    return MEDIUM_CRAFT.get(m, MEDIUM_CRAFT[Medium.NOVEL])


def craft_brief(medium: Medium | str | None) -> str:
    """渲染成注入提示词的形态说明块。

    刻意包含 `sample`：只给规则不给样例，模型会照着它对「剧本」的印象写，
    而不是照着本项目的格式写 —— 而下游渲染器解析的是本项目的格式。
    """
    c = craft_for(medium)
    return (
        f"【写作形态：{c.label}】\n"
        f"身份：{c.role}\n"
        f"格式（硬约束）：\n{c.form}\n\n"
        f"本媒介禁止：\n{c.bans}\n\n"
        f"正确样例（照这个形态写，不要照它抄内容）：\n{c.sample}"
    )


def length_hint(medium: Medium | str | None, target_words: int) -> str:
    """把字数目标换算成该媒介的长度直觉。

    换算系数是行业粗估（见模块 docstring），只用于给模型量级感。
    小说类直接说字数，不换算 —— 换算了反而更模糊。
    """
    c = craft_for(medium)
    if c.unit == "字":
        return f"约 {target_words} 字。"
    units = max(1, round(target_words / c.words_per_unit))
    extra = ""
    if c.unit == "页":
        # 行业惯例：一页剧本约合银幕一分钟。
        extra = f"，约合银幕 {units} 分钟"
    return f"约 {target_words} 字（按{c.unit}计约 {units} {c.unit}{extra}）。"
