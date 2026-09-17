"""渲染器 —— IR 的多后端。

核心论点：文本只是 IR 的一个「视图」。
同一个 Narrative IR，换一个 renderer 就是另一种媒介。

    小说正文      text.py        ← 1.0 交付物
    Fountain 剧本  fountain.py    ← 1.0 交付物（影视剧本）
    漫画分镜 JSON  storyboard.py  ← 2.0（定义 schema，填补行业空白）
    Ink 脚本       ink.py         ← 2.0 互动小说
    Ren'Py 脚本    renpy.py       ← 2.0 galgame
"""

from .fountain import render_fountain
from .html import render_html
from .ink import render_ink
from .renpy import render_renpy
from .storyboard import render_storyboard
from .text import render_text

__all__ = [
    "render_text",
    "render_fountain",
    "render_storyboard",
    "render_ink",
    "render_renpy",
    "render_html",
]
