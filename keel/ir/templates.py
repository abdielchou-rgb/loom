"""结构模板插件。

设计原则：一个方法论 = { beats[], validators[], prompt_fragments } 三件套。

方法论不是 prompt 前缀，而是「结构骨架的求解约束」+「结构体检的判据」。
内置模板刻意包含彼此冲突的体系（好莱坞 beat sheet 与起承转合），
以证明系统是方法论中立的 —— 这是差异化卖点，也是诚实做法。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import ArcShape, Medium


class BeatSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    position: tuple[float, float] = Field(
        description="相对位置区间 (起, 止)，0.0 - 1.0"
    )
    purpose: str
    required: bool = True


class BeatTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    origin: str
    media: list[Medium] = Field(default_factory=list)
    beats: list[BeatSpec]
    validators: list[str] = Field(default_factory=list)
    prompt_fragments: dict[str, str] = Field(default_factory=dict)
    notes: str = ""

    def beat_at(self, progress: float) -> BeatSpec | None:
        """按进度 (0-1) 定位所处节拍。"""
        for b in self.beats:
            lo, hi = b.position
            if lo <= progress < hi:
                return b
        return self.beats[-1] if self.beats else None


# ---------------------------------------------------------------------------
# 好莱坞派
# ---------------------------------------------------------------------------

SAVE_THE_CAT = BeatTemplate(
    id="save_the_cat",
    name="Save the Cat 15 节拍",
    origin="Blake Snyder (2005)",
    media=[Medium.SCREENPLAY, Medium.NOVEL, Medium.WEB_NOVEL],
    beats=[
        BeatSpec(id="opening_image", name="开场画面", position=(0.00, 0.01),
                 purpose="改变前的世界快照"),
        BeatSpec(id="theme_stated", name="主题呈现", position=(0.01, 0.05),
                 purpose="主题提示，通常由他人说出"),
        BeatSpec(id="setup", name="铺垫", position=(0.05, 0.10),
                 purpose="建立现状与主角缺陷"),
        BeatSpec(id="catalyst", name="催化剂", position=(0.10, 0.12),
                 purpose="激励事件，世界改变"),
        BeatSpec(id="debate", name="争论", position=(0.12, 0.20),
                 purpose="犹豫，是否行动"),
        BeatSpec(id="break_into_two", name="进入第二幕", position=(0.20, 0.25),
                 purpose="主动追求开始"),
        BeatSpec(id="b_story", name="B 故事", position=(0.25, 0.30),
                 purpose="副线，承载主题"),
        BeatSpec(id="fun_and_games", name="游戏与乐趣", position=(0.30, 0.50),
                 purpose="承诺的前提兑现"),
        BeatSpec(id="midpoint", name="中点", position=(0.50, 0.55),
                 purpose="假胜利或假失败，赌注升级"),
        BeatSpec(id="bad_guys_close_in", name="坏人逼近", position=(0.55, 0.65),
                 purpose="压力持续累积"),
        BeatSpec(id="all_is_lost", name="一无所有", position=(0.65, 0.75),
                 purpose="最低点"),
        BeatSpec(id="dark_night", name="灵魂黑夜", position=(0.75, 0.78),
                 purpose="沉浸于黑暗"),
        BeatSpec(id="break_into_three", name="进入第三幕", position=(0.78, 0.80),
                 purpose="顿悟，主角理解新事物"),
        BeatSpec(id="finale", name="终局", position=(0.80, 0.99),
                 purpose="高潮与最终对决"),
        BeatSpec(id="final_image", name="终场画面", position=(0.99, 1.01),
                 purpose="开场画面的镜像，全新平衡"),
    ],
    validators=[
        "mirror_bookends",
        "value_charge_flip",
        "commitment_satisfied",
    ],
    notes=(
        "Snyder 的 Final Image 与 Opening Image 互为镜像，是完整 Sa→Sa' 回路的标志。"
        "注意：Bordwell 指出好莱坞规范是历史偶然的惯例而非法则；"
        "beat sheet 的错误在于把语料当成了语法。本系统因此把它做成可插拔模板。"
    ),
)

THREE_ACT = BeatTemplate(
    id="three_act",
    name="三幕结构",
    origin="Syd Field / 通用",
    media=[Medium.SCREENPLAY, Medium.NOVEL],
    beats=[
        BeatSpec(id="act1", name="第一幕·建置", position=(0.00, 0.25),
                 purpose="世界、人物、激励事件"),
        BeatSpec(id="act2a", name="第二幕上·对抗", position=(0.25, 0.50),
                 purpose="障碍升级"),
        BeatSpec(id="midpoint", name="中点", position=(0.50, 0.55),
                 purpose="方向反转"),
        BeatSpec(id="act2b", name="第二幕下·瓦解", position=(0.55, 0.75),
                 purpose="全面溃败"),
        BeatSpec(id="act3", name="第三幕·解决", position=(0.75, 1.01),
                 purpose="高潮与收束"),
    ],
    validators=["value_charge_flip", "state_delta"],
)

# ---------------------------------------------------------------------------
# 神话派（Campbell → Vogler）
# ---------------------------------------------------------------------------

# 来源：Joseph Campbell《千面英雄》(1949) 的一元神话「分离 → 启蒙 → 回归」，
# 经 Christopher Vogler《作家之旅》(1992) 简化为可操作的 12 阶段。
# 豆瓣：作家之旅 8.4（1226 人）/ 英雄之旅 25 周年纪念版 9.1 / 千面英雄 8.3（2159 人）。
#
# 为什么单独注册、不并入 save_the_cat：它们**不是同一层的东西** ——
# 救猫咪是「节拍表」（外部事件的时间分布），英雄之旅是「原型旅程」
# （角色的心理阶段）。同一个故事可以同时过两套检查而不矛盾。
# 局限（必须写明）：此模板**只适用于成长型叙事**。群像剧、悲剧、
# 反英雄故事套上去会误报 —— 这也是 Vogler 本人的提醒。
HERO_JOURNEY = BeatTemplate(
    id="hero_journey",
    name="英雄之旅 12 阶段",
    origin="Campbell (1949) → Vogler《作家之旅》(1992)",
    media=[Medium.SCREENPLAY, Medium.NOVEL, Medium.WEB_NOVEL],
    beats=[
        BeatSpec(id="ordinary_world", name="普通世界", position=(0.00, 0.08),
                 purpose="展现主角的日常与缺失，建立「之前」的基线"),
        BeatSpec(id="call_to_adventure", name="冒险的召唤", position=(0.08, 0.13),
                 purpose="一个问题或挑战打破了日常"),
        BeatSpec(id="refusal", name="拒绝召唤", position=(0.13, 0.18),
                 purpose="主角因恐惧而犹豫 —— 没有拒绝就没有真实的风险"),
        BeatSpec(id="meeting_mentor", name="遇见导师", position=(0.18, 0.23),
                 purpose="获得装备、忠告或信念（导师可以是人也可以是物）"),
        BeatSpec(id="first_threshold", name="跨越第一道门槛", position=(0.23, 0.28),
                 purpose="不可逆地进入非常世界，退路关闭"),
        BeatSpec(id="tests_allies", name="试炼·盟友·敌人", position=(0.28, 0.45),
                 purpose="学习规则，建立关系，暴露弱点"),
        BeatSpec(id="inmost_cave", name="逼近最深的洞穴", position=(0.45, 0.52),
                 purpose="接近核心恐惧所在，做准备与最后犹豫"),
        BeatSpec(id="ordeal", name="严酷的考验", position=(0.52, 0.60),
                 purpose="与死亡（字面或象征）正面相遇，旧我死去"),
        BeatSpec(id="reward", name="获得奖赏", position=(0.60, 0.68),
                 purpose="拿到想要的东西，但代价已经付出"),
        BeatSpec(id="road_back", name="归途", position=(0.68, 0.75),
                 purpose="被追逐或自我怀疑，决定不带着奖赏逃跑"),
        BeatSpec(id="resurrection", name="复活", position=(0.75, 0.90),
                 purpose="最后一次考验：用新的自己去面对旧的恐惧"),
        BeatSpec(id="return_elixir", name="带着灵药归来", position=(0.90, 1.00),
                 purpose="回到普通世界并改变它 —— 证明转变真的发生了"),
    ],
    validators=["value_charge_flip", "lie_arc_closure"],
    notes="只适用于成长型叙事；群像剧 / 悲剧 / 反英雄会误报。",
)

# 来源：Paul Gulino《序列编剧法》(2004) —— 一部 120 页剧本切成 8 个序列，
# 每个序列约 15 分钟、有自己的小高潮。豆瓣 7.8（166 人）。
# 价值在于补上**幕与场景之间缺失的中间粒度**：Keel 此前只有场景级
# （value_charge_flip）和幕级（three_act）检查，没有序列级。
# 8 个序列按幕均分（第一幕 2 / 第二幕 4 / 第三幕 2）是 Gulino 的标准分法。
SEQUENCE_8 = BeatTemplate(
    id="sequence_8",
    name="八序列（幕与场景的中间粒度）",
    origin="Paul Gulino《序列编剧法》(2004)",
    media=[Medium.SCREENPLAY, Medium.MICRO_DRAMA],
    beats=[
        BeatSpec(id="seq1", name="序列 1 · 建置与激励", position=(0.000, 0.125),
                 purpose="第一幕：确立日常，抛出激励事件"),
        BeatSpec(id="seq2", name="序列 2 · 锁定目标", position=(0.125, 0.250),
                 purpose="第一幕：主角做出承诺，跨入新世界"),
        BeatSpec(id="seq3", name="序列 3 · 首次障碍", position=(0.250, 0.375),
                 purpose="第二幕上半：新世界的规则与阻力显现"),
        BeatSpec(id="seq4", name="序列 4 · 中点", position=(0.375, 0.500),
                 purpose="第二幕上半：中点转折，赌注升级"),
        BeatSpec(id="seq5", name="序列 5 · 逼紧", position=(0.500, 0.625),
                 purpose="第二幕下半：反作用力压上，退路消失"),
        BeatSpec(id="seq6", name="序列 6 · 一无所有", position=(0.625, 0.750),
                 purpose="第二幕下半：最低点，旧我死亡"),
        BeatSpec(id="seq7", name="序列 7 · 最后决断", position=(0.750, 0.875),
                 purpose="第三幕：以新认知做出不可逆的选择"),
        BeatSpec(id="seq8", name="序列 8 · 高潮与收束", position=(0.875, 1.000),
                 purpose="第三幕：高潮兑现，新常态确立"),
    ],
    validators=["value_charge_flip"],
    notes="每序列应有自己的小高潮；只给粒度，不替代幕级结构判断。",
)

# ---------------------------------------------------------------------------
# 东亚派
# ---------------------------------------------------------------------------

KISHOTENKETSU = BeatTemplate(
    id="kishotenketsu",
    name="起承转合",
    origin="东亚传统（汉诗/汉文→日式四段）",
    media=[Medium.NOVEL, Medium.WEB_NOVEL, Medium.MICRO_DRAMA,
           Medium.VISUAL_NOVEL, Medium.COMIC],
    beats=[
        BeatSpec(id="ki", name="起", position=(0.00, 0.25), purpose="引入"),
        BeatSpec(id="sho", name="承", position=(0.25, 0.50),
                 purpose="承接发展，不必然升高冲突"),
        BeatSpec(id="ten", name="转", position=(0.50, 0.75),
                 purpose="转折/意外视角，可与前文无直接冲突关系"),
        BeatSpec(id="ketsu", name="合", position=(0.75, 1.01),
                 purpose="收束与统一"),
    ],
    validators=["state_delta"],
    notes=(
        "关键差异：转不必是冲突的升级。这与西方三幕/beat sheet 的根本假设不同，"
        "对日常系、galgame 日常线、治愈系内容是不可替代的模板。"
    ),
)

ZHANGHUI = BeatTemplate(
    id="zhanghui",
    name="章回体（连载单元）",
    origin="明清章回小说传统",
    media=[Medium.WEB_NOVEL, Medium.NOVEL],
    beats=[
        BeatSpec(id="huimu", name="回目", position=(0.00, 0.05),
                 purpose="对偶标题，预告本回内容"),
        BeatSpec(id="ruhua", name="入话", position=(0.05, 0.15),
                 purpose="承接上回，交代处境"),
        BeatSpec(id="zhengzhuan", name="正传", position=(0.15, 0.80),
                 purpose="本回自足的核心事件"),
        BeatSpec(id="duanzhang", name="断章", position=(0.80, 1.01),
                 purpose="悬念收束，钩住追读"),
    ],
    validators=["state_delta", "enigma_progress"],
    notes="回目 = 自足单元 + 悬念 + 对偶标题。可直接复用为连载 schema。",
)

# ---------------------------------------------------------------------------
# 短剧派
# ---------------------------------------------------------------------------

MICRO_DRAMA = BeatTemplate(
    id="micro_drama",
    name="微短剧单集节拍",
    origin="中国短剧行业操作惯例",
    media=[Medium.MICRO_DRAMA],
    beats=[
        BeatSpec(id="hook_3s", name="三秒抓人", position=(0.00, 0.08),
                 purpose="冲突/冲击画面/悬念/反转，前 3 秒必须成立"),
        BeatSpec(id="recap", name="回扣", position=(0.08, 0.10),
                 purpose="极简前情"),
        BeatSpec(id="scene", name="场景推进", position=(0.10, 0.25),
                 purpose="建立本集情境"),
        BeatSpec(id="core_event", name="核心事件", position=(0.25, 0.67),
                 purpose="本集主戏"),
        BeatSpec(id="reversal", name="反转", position=(0.67, 0.92),
                 purpose="小反转每 5-10 集，大反转每 20-30 集"),
        BeatSpec(id="hook_end", name="钩子", position=(0.92, 1.01),
                 purpose="集末悬念，驱动下一集"),
    ],
    validators=["hook_cadence", "paywall_gate_present"],
    notes=(
        "行业惯例（非平台公开规格，应做成可配置参数）："
        "60-100 集，1-3 分钟/集，300-800 字/集，钩子每 30-60 秒，"
        "付费卡点约在 8-12 / 26-30 / 60 集。"
        "付费边界是一等结构节点，不是商业附注。"
    ),
)

# ---------------------------------------------------------------------------
# 数据驱动派
# ---------------------------------------------------------------------------

ARC_SHAPE_TEMPLATES: dict[ArcShape, BeatTemplate] = {
    ArcShape.RAGS_TO_RICHES: BeatTemplate(
        id="arc_rags_to_riches",
        name="情感弧线·白手起家",
        origin="Reagan et al. 2016, EPJ Data Science（实证聚类）",
        media=[Medium.NOVEL, Medium.WEB_NOVEL, Medium.SCREENPLAY],
        beats=[
            BeatSpec(id="rise_a", name="持续上升·前段", position=(0.00, 0.33),
                     purpose="稳定上行"),
            BeatSpec(id="rise_b", name="持续上升·中段", position=(0.33, 0.66),
                     purpose="稳定上行"),
            BeatSpec(id="rise_c", name="持续上升·后段", position=(0.66, 1.01),
                     purpose="稳定上行"),
        ],
        validators=["emotion_curve_match"],
    ),
    ArcShape.TRAGEDY: BeatTemplate(
        id="arc_tragedy",
        name="情感弧线·悲剧",
        origin="Reagan et al. 2016",
        media=[Medium.NOVEL, Medium.SCREENPLAY],
        beats=[
            BeatSpec(id="fall_a", name="持续下落·前段", position=(0.00, 0.33),
                     purpose="稳定下行"),
            BeatSpec(id="fall_b", name="持续下落·中段", position=(0.33, 0.66),
                     purpose="稳定下行"),
            BeatSpec(id="fall_c", name="持续下落·后段", position=(0.66, 1.01),
                     purpose="稳定下行"),
        ],
        validators=["emotion_curve_match"],
    ),
    ArcShape.MAN_IN_A_HOLE: BeatTemplate(
        id="arc_man_in_a_hole",
        name="情感弧线·洞里的人",
        origin="Reagan et al. 2016",
        media=[Medium.NOVEL, Medium.SCREENPLAY],
        beats=[
            BeatSpec(id="down", name="下落", position=(0.00, 0.35), purpose="恶化"),
            BeatSpec(id="bottom", name="谷底", position=(0.35, 0.50), purpose="最低点"),
            BeatSpec(id="up", name="回升", position=(0.50, 1.01), purpose="好转"),
        ],
        validators=["emotion_curve_match"],
    ),
    ArcShape.ICARUS: BeatTemplate(
        id="arc_icarus",
        name="情感弧线·伊卡洛斯",
        origin="Reagan et al. 2016",
        media=[Medium.NOVEL, Medium.SCREENPLAY],
        beats=[
            BeatSpec(id="up", name="上升", position=(0.00, 0.50), purpose="攀升"),
            BeatSpec(id="down", name="坠落", position=(0.50, 1.01), purpose="崩塌"),
        ],
        validators=["emotion_curve_match"],
    ),
    ArcShape.CINDERELLA: BeatTemplate(
        id="arc_cinderella",
        name="情感弧线·灰姑娘",
        origin="Reagan et al. 2016",
        media=[Medium.NOVEL, Medium.SCREENPLAY],
        beats=[
            BeatSpec(id="rise", name="上升", position=(0.00, 0.35), purpose="上行"),
            BeatSpec(id="fall", name="下落", position=(0.35, 0.60), purpose="回落"),
            BeatSpec(id="rise2", name="再上升", position=(0.60, 1.01), purpose="终局上行"),
        ],
        validators=["emotion_curve_match"],
    ),
    ArcShape.OEDIPUS: BeatTemplate(
        id="arc_oedipus",
        name="情感弧线·俄狄浦斯",
        origin="Reagan et al. 2016",
        media=[Medium.NOVEL, Medium.SCREENPLAY],
        beats=[
            BeatSpec(id="fall", name="下落", position=(0.00, 0.35), purpose="下行"),
            BeatSpec(id="rise", name="上升", position=(0.35, 0.60), purpose="回升"),
            BeatSpec(id="fall2", name="再下落", position=(0.60, 1.01), purpose="终局崩塌"),
        ],
        validators=["emotion_curve_match"],
    ),
}

# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, BeatTemplate] = {
    t.id: t
    for t in [
        SAVE_THE_CAT,
        THREE_ACT,
        HERO_JOURNEY,
        SEQUENCE_8,
        KISHOTENKETSU,
        ZHANGHUI,
        MICRO_DRAMA,
        *ARC_SHAPE_TEMPLATES.values(),
    ]
}


def get_template(template_id: str) -> BeatTemplate:
    if template_id not in _REGISTRY:
        raise KeyError(
            f"未知结构模板: {template_id!r}。可用: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[template_id]


def list_templates(medium: Medium | None = None) -> list[BeatTemplate]:
    items = list(_REGISTRY.values())
    if medium is not None:
        items = [t for t in items if not t.media or medium in t.media]
    return items


def suggest_templates(arc: ArcShape) -> list[BeatTemplate]:
    """按情感弧线推荐结构模板。数据驱动的模板与大师模板平级。"""
    out = [ARC_SHAPE_TEMPLATES[arc]]
    out.extend(t for t in _REGISTRY.values() if t.id != ARC_SHAPE_TEMPLATES[arc].id)
    return out
