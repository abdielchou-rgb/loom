"""IR 枚举。

设计依据：
- Focalization / Frequency  <- Genette《Narrative Discourse》
- EnigmaState               <- Barthes《S/Z》阐释符码
- ActantRole                <- Greimas 行动元模型
- SceneOutcome              <- Writing Excuses / Sanderson 的 yes-but / no-and
- Severity                  <- 校验器输出分级
"""

from __future__ import annotations

from enum import Enum


class Focalization(str, Enum):
    """Genette 的聚焦模式（谁感知）。"""

    ZERO = "zero"           # 全知
    INTERNAL = "internal"   # 内聚焦：通过某角色的意识
    EXTERNAL = "external"   # 外聚焦：只呈现行为，不进意识


class Frequency(str, Enum):
    """Genette 的叙事频率。"""

    SINGULATIVE = "singulative"   # 发生一次，讲一次
    REPETITIVE = "repetitive"     # 发生一次，讲多次（罗生门式）
    ITERATIVE = "iterative"       # 发生多次，讲一次（"那年夏天他每天…"）


class EnigmaState(str, Enum):
    """Barthes 阐释符码的状态机。"""

    POSED = "posed"         # 提出
    DELAYED = "delayed"     # 延宕
    PARTIAL = "partial"     # 部分揭示
    RESOLVED = "resolved"   # 解消
    ABANDONED = "abandoned"  # 被遗弃（= 烂尾信号）


class ActantRole(str, Enum):
    """Greimas 的六个行动元。

    关键：行动元是「角色位」，不是「人物」。
    同一个人物占据两个行动元 = 反转的自动检测信号。
    """

    SUBJECT = "subject"
    OBJECT = "object"
    SENDER = "sender"
    RECEIVER = "receiver"
    HELPER = "helper"
    OPPONENT = "opponent"


class SceneOutcome(str, Enum):
    """场景结果。比「转折」更可校验。"""

    YES = "yes"            # 主角达成目标
    YES_BUT = "yes_but"    # 达成，但代价
    NO = "no"              # 未达成
    NO_AND = "no_and"      # 未达成，且更糟


class EntityKind(str, Enum):
    CHARACTER = "character"
    LOCATION = "location"
    ITEM = "item"
    ORGANIZATION = "organization"
    CONCEPT = "concept"


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class ArcShape(str, Enum):
    """Reagan et al. 2016 (EPJ Data Science) 实证得到的六种情感弧线。

    注意：这六种里没有一种是三幕结构。它们与 Save the Cat 平级，
    作为「从数据导出的模板」内建。
    """

    RAGS_TO_RICHES = "rags_to_riches"
    TRAGEDY = "tragedy"
    MAN_IN_A_HOLE = "man_in_a_hole"
    ICARUS = "icarus"
    CINDERELLA = "cinderella"
    OEDIPUS = "oedipus"


class Medium(str, Enum):
    NOVEL = "novel"
    WEB_NOVEL = "web_novel"        # 网文：追读率是目标函数
    SCREENPLAY = "screenplay"
    MICRO_DRAMA = "micro_drama"    # 短剧：付费卡点是结构参数
    INTERACTIVE_FICTION = "interactive_fiction"
    VISUAL_NOVEL = "visual_novel"  # galgame
    COMIC = "comic"
    MURDER_MYSTERY = "murder_mystery"  # 剧本杀


class ChunkOrigin(str, Enum):
    """内容来源 —— 合规计量与溯源的基础。"""

    HUMAN = "human"
    AI_GENERATED = "ai_generated"
    AI_ASSISTED = "ai_assisted"    # 人工主导 + AI 润色
    AI_EDITED = "ai_edited"        # AI 生成 + 人工修改
    IMPORTED = "imported"


class InsertPosition(str, Enum):
    """lorebook 注入位置（对齐 SillyTavern World Info）。"""

    BEFORE_CHAR_DEFS = "before_char_defs"
    AFTER_CHAR_DEFS = "after_char_defs"
    BEFORE_EXAMPLES = "before_examples"
    AFTER_EXAMPLES = "after_examples"
    TOP_OF_AN = "top_of_author_note"
    BOTTOM_OF_AN = "bottom_of_author_note"
    AT_DEPTH = "at_depth"     # 以 depth + role 指定
    OUTLET = "outlet"         # 手动拉取


class KeyLogic(str, Enum):
    AND_ANY = "and_any"
    AND_ALL = "and_all"
    NOT_ANY = "not_any"
    NOT_ALL = "not_all"
