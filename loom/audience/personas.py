"""观众人格库。

**关键设计立场：人格不是人口统计学，是行为参数。**

「25 岁男性」这种描述没有可执行含义 —— 你没法用它算任何东西。
真正能驱动预测的是行为敏感度：他多需要反转、多不能忍慢节奏、
对文字质量多挑剔、单场能消化多少信息、耐心底线在哪。

这样定义带来三个好处：
  1. 参数可直接拟合到真实留存数据（见 simulator.calibrate）
  2. 参数是显式的、可辩论的 —— 团队可以吵「这个人群到底多需要反转」
     而不是吵「LLM 说的对不对」
  3. 2.0 阶段可把同一个模型搬到互动叙事玩家上，只换参数不换引擎

来源：CHI 2025 编剧研究（arXiv 2502.16153）显示编剧最想要的 AI 角色是
「观众」—— 23 位受访者中，结构/对白/文风环节明确拒绝 AI，但愿意接受
一个能替他们预演观众反应的 AI。这是本模块存在的理由。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Persona:
    """一个可计算的行为人格。所有参数都在 [0,1] 或计数域内。"""

    id: str
    label: str
    platform: str
    notes: str = ""

    # -- 耐受与偏好（0 = 完全不在意，1 = 极度敏感）--
    twist_appetite: float = 0.5
    """对反转/价值翻转的需求强度。低 = 看日常流也能看下去。"""

    curiosity: float = 0.5
    """对未解之谜的粘性。高 = 没有悬念就走。"""

    prose_standard: float = 0.5
    """对文字质量的标准。高 = 文笔差就直接弃。"""

    pacing_standard: float = 0.5
    """对节奏的挑剔度。高 = 一场没推进就弃。"""

    payoff_need: float = 0.5
    """对「给到」的需求。高 = 埋了不收就骂。"""

    # -- 容量与底线 --
    max_info_density: int = 3
    """单场可消化的谜题动作数。超过即过载。"""

    base_hazard: float = 0.06
    """基础单场流失率（无任何风险因素时）。"""

    drop_floor: float = 0.55
    """留存跌破此值即判定弃剧。"""

    weight: float = 1.0
    """该人群在总量中的占比权重（用于加权汇总）。"""

    def __post_init__(self) -> None:
        for name in (
            "twist_appetite",
            "curiosity",
            "prose_standard",
            "pacing_standard",
            "payoff_need",
        ):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{self.id}.{name} 必须在 [0,1]，实际 {v}")


# ---------------------------------------------------------------------------
# 人格库
# ---------------------------------------------------------------------------

BINGE_WEB_NOVEL = Persona(
    id="binge_web_novel",
    label="追更型网文读者",
    platform="起点 / 番茄",
    twist_appetite=0.80,
    curiosity=0.85,
    prose_standard=0.25,
    pacing_standard=0.85,
    payoff_need=0.60,
    max_info_density=3,
    base_hazard=0.05,
    drop_floor=0.55,
    weight=1.0,
    notes=(
        "每章必须有推进，否则直接切书。文笔容忍度极高 —— 句子糙没关系，"
        "但「这章啥也没发生」是死罪。对钩子的敏感度是所有人格里最高的。"
    ),
)

COMMUTER_MOBILE = Persona(
    id="commuter_mobile",
    label="碎片时间手机读者",
    platform="抖音短剧 / 番茄免费",
    twist_appetite=0.90,
    curiosity=0.70,
    prose_standard=0.10,
    pacing_standard=0.95,
    payoff_need=0.85,
    max_info_density=2,
    base_hazard=0.10,
    drop_floor=0.60,
    weight=1.0,
    notes=(
        "注意力以 30-60 秒为单位。前 3 秒没抓住就走。"
        "这解释了短剧为什么必须开场即冲突、每集末留钩子 —— "
        "不是审美选择，是这个人群的 hazard 参数决定的。"
    ),
)

PRESTIGE_VIEWER = Persona(
    id="prestige_viewer",
    label="精品剧观众",
    platform="Netflix / 长视频",
    twist_appetite=0.55,
    curiosity=0.75,
    prose_standard=0.80,
    pacing_standard=0.45,
    payoff_need=0.70,
    max_info_density=5,
    base_hazard=0.03,
    drop_floor=0.50,
    weight=0.6,
    notes=(
        "容忍慢节奏，但不能容忍廉价。真正会让他弃剧的是「AI 味」和"
        "「一眼看穿的套路」，而不是「这一场没推进」。"
        "与他对应的是反 slop 模块而不是钩子密度校验器。"
    ),
)

GENRE_CRITIC = Persona(
    id="genre_critic",
    label="类型评论者",
    platform="豆瓣 / 知乎 / B 站",
    twist_appetite=0.70,
    curiosity=0.80,
    prose_standard=0.75,
    pacing_standard=0.70,
    payoff_need=0.95,
    max_info_density=5,
    base_hazard=0.02,
    drop_floor=0.35,
    weight=0.35,
    notes=(
        "几乎不会中途弃，但会在结尾集中开火。payoff_need 拉满 —— "
        "烂尾在他这里等于全盘否定。是「承诺未兑现」校验器的人形版本。"
    ),
)

CASUAL_INTERACTIVE = Persona(
    id="casual_interactive",
    label="休闲互动叙事玩家",
    platform="橙光 / 易次元 / 视觉小说",
    twist_appetite=0.60,
    curiosity=0.55,
    prose_standard=0.35,
    pacing_standard=0.60,
    payoff_need=0.75,
    max_info_density=3,
    base_hazard=0.08,
    drop_floor=0.55,
    weight=0.5,
    notes=(
        "2.0 阶段的观众。与读者最大的区别是：他对**能动性**敏感而不是对节奏 —— "
        "连续三屏没有选择会让他觉得「那我还不如看小说」。"
        "对应的是 Director 层的选择密度，不是本文的 hazard 模型。"
    ),
)


LIBRARY: dict[str, Persona] = {
    p.id: p
    for p in (
        BINGE_WEB_NOVEL,
        COMMUTER_MOBILE,
        PRESTIGE_VIEWER,
        GENRE_CRITIC,
        CASUAL_INTERACTIVE,
    )
}


def get_persona(pid: str) -> Persona:
    if pid not in LIBRARY:
        raise KeyError(f"未知人格 {pid!r}；可选：{sorted(LIBRARY)}")
    return LIBRARY[pid]


def select(personas: list[str] | None = None) -> list[Persona]:
    """按 id 列表取人格；None 表示全部。"""
    if personas is None:
        return list(LIBRARY.values())
    return [get_persona(p) for p in personas]


def panel(medium: str) -> list[Persona]:
    """按媒介给出推荐评审团 —— 不同媒介的真实观众构成不同。"""
    if medium in ("micro_drama",):
        return [COMMUTER_MOBILE, BINGE_WEB_NOVEL, GENRE_CRITIC]
    if medium in ("screenplay",):
        return [PRESTIGE_VIEWER, COMMUTER_MOBILE, GENRE_CRITIC]
    if medium in ("interactive_fiction", "visual_novel"):
        return [CASUAL_INTERACTIVE, BINGE_WEB_NOVEL, PRESTIGE_VIEWER]
    # novel / web_novel 默认
    return [BINGE_WEB_NOVEL, COMMUTER_MOBILE, PRESTIGE_VIEWER, GENRE_CRITIC]
