"""媒介策略闸门 —— 把「合规」从文档里搬进代码。

── 为什么要有这个模块 ─────────────────────────────────────────────
调研结论 F6：

> 网文三平台（起点 / 番茄 / 晋江）**一致禁止 AI 直出正文**
> （起点 >10% 即处理，方式为「去流量化」）；
> 微短剧**只要求加标识**（《微短剧发展管理办法》第 34 条）。
>
> **同一个 Keel：做网文是「违规工具」，做剧本是「合规工具」。**

这条结论此前只存在于 `MEMORY.md` 与调研文档里 —— **知识在文档里，不在代码里**。
后果是：代码完全不知道这件事，`render_text()` 对任何媒介一视同仁地出正文。

本模块把这条知识变成一道**可机检的闸门**。

── 设计原则：策略，不是删除 ───────────────────────────────────────
**不要**删掉网文正文生成能力。理由：

1. **这个判断可能变。** 平台口径在动（2026 年 4 月阅文联合 16 家平台签
   《反洗稿自律公约》，7–8 月三家口径又各调过一次）。把能力删掉，
   政策一松就要重写；做成闸门，政策一松改一行。
2. **有些场景是合法的。** 作者写网文草稿供自己改写到 >30%，
   或用于不投稿的私人写作 —— 这些不该被工具挡住。

所以：**默认挡，显式放行，放行留痕。**

── 为什么只挡 `WEB_NOVEL`，不挡 `NOVEL` ───────────────────────────
`NOVEL` 是「小说」这个媒介，`WEB_NOVEL` 是「发布到网文平台」这个场景。
被平台禁止的是**后者**（起点 / 番茄 / 晋江的口径针对的是投稿作品）。
一部不投向网文平台的小说，不受这条约束。

把两者一起挡掉是**过度执行** —— 那会让 `NOVEL` 媒介的既有用法
（`scripts/pipeline_demo.py` 等）全部失效，而这些用法并不违规。

── 刻意不做的事 ───────────────────────────────────────────────────
* **不检测、不评判已有正文的 AI 占比。** 那是 `ProvenanceLedger` 与
  `selfcheck` 的职责；本模块只管「要不要生产」。
* **不替作者做决定。** 闸门给出理由与放行开关，决定由作者下 ——
  Keel 的立场是「AI 帮你写」，不是「AI 替你写」，也不是「AI 管着你」。
"""

from __future__ import annotations

from .ir.enums import Medium

__all__ = [
    "PROSE_BLOCKED_MEDIA",
    "PolicyError",
    "prose_allowed",
    "blocked_reason",
    "OverriddenProse",
]

#: 默认**不产出正文**的媒介。理由见模块 docstring。
PROSE_BLOCKED_MEDIA: frozenset[Medium] = frozenset({Medium.WEB_NOVEL})

#: 放行时的说明文案。必须写清「这是作者的决定，不是 Keel 的推荐」。
_OVERRIDE_NOTICE = (
    "你已显式放行网文正文生成。请注意：起点 / 番茄 / 晋江 三家平台"
    "**一致禁止 AI 直出正文**（起点 >10% 即处理，方式为「去流量化」而非下架）。"
    "本功能面向「自己写草稿再人工改写到平台要求」的场景，"
    "**不是**投稿捷径。是否合规由你负责，Keel 不提供保证。"
)


class PolicyError(RuntimeError):
    """违反媒介策略。默认策略可以被显式放行，所以这是**可恢复**的错误。"""


def blocked_reason(medium: Medium) -> str | None:
    """返回该媒介被挡的原因；不挡则返回 `None`。"""
    if medium not in PROSE_BLOCKED_MEDIA:
        return None
    return (
        f"「{medium.value}」默认**不生成正文** —— "
        "起点 / 番茄 / 晋江 三家网文平台一致禁止 AI 直出正文"
        "（起点 AI 占比 >10% 即处理，方式为移出全部榜单/推荐位）。"
        "Keel 在网文场景下提供的是**结构 + 伏笔表 + 人设卡 + 合规自检**，"
        "不是代笔。详见 keel/policy.py 的说明。"
    )


def prose_allowed(medium: Medium, *, override: bool = False) -> bool:
    """该媒介是否允许生成正文。"""
    if medium not in PROSE_BLOCKED_MEDIA:
        return True
    return bool(override)


class OverriddenProse:
    """一次**已留痕**的放行。

    为什么留痕：合规争议发生时，需要能说清「这份正文是作者显式要求生成的，
    并且当时已经被告知风险」。这和 `ProvenanceLedger` 是同一类思路 ——
    「记录」本身就是产品能力，不是附加功能。

    用法::

        with OverriddenProse(Medium.WEB_NOVEL) as ov:
            render_text(ir, force_prose=True)
        ov.notice  # 放行说明，打印给用户
    """

    def __init__(self, medium: Medium) -> None:
        self.medium = medium
        self.notice = _OVERRIDE_NOTICE
        self.used = False

    def __enter__(self) -> "OverriddenProse":
        self.used = True
        return self

    def __exit__(self, *exc) -> None:
        return None

    def __repr__(self) -> str:
        return f"OverriddenProse({self.medium.value}, used={self.used})"
