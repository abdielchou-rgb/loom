"""IR 的唯一加载入口。

**为什么单独一个文件**：同一个动作（「把磁盘上的 IR 读成对象」）有两个消费方，
而它们对**失败**的表达方式必须不同：

    * `keel/cli.py`   面向人   -> 说人话的 SystemExit（「先跑 keel write 生成一个」）
    * `keel/api.py`   面向插件 -> 结构化错误（插件解析不了 traceback，也解析不了中文）

如果两边各写一份 `NarrativeIR.from_json(p.read_text(...))`，那么「怎么算读得出来」
这件事就有了两个实现 —— 加一个校验、改一次编码、换一次 pydantic 调用方式，
都得改两处，而**没有任何测试会因为你只改了一处而变红**。

所以这里只做一件事：**把「读不出来」归一成一个带 `kind` 的异常**，
由调用方决定怎么翻译。这与 `medium_craft.split_slugline()`（地点解析唯一实现）
和 `lore` 的激活判据是同一条纪律：
**同一件事只有一个实现，不同的只是呈现。**
"""

from __future__ import annotations

from pathlib import Path

from .models import NarrativeIR


class IRLoadError(Exception):
    """读不出 IR。

    `kind` 是**给程序看**的（调用方按它分支），`reason` 是**给人看**的原文。
    不要只留一个字符串消息然后让调用方 `if "不存在" in str(exc)` —— 那是
    把判据建在文案上，文案一改就静默走错分支。
    """

    #: 路径不存在（或不是文件）。通常意味着「还没生成过」。
    MISSING = "missing"
    #: 文件在，但读不出 / 不是合法 IR（JSON 截断、字段非法、版本不对）。
    UNREADABLE = "unreadable"

    def __init__(self, kind: str, path: Path, reason: str) -> None:
        super().__init__(f"{kind}: {path}: {reason}")
        self.kind = kind
        self.path = path
        self.reason = reason


def load_ir(path: str | Path) -> NarrativeIR:
    """把一份 IR 读成 `NarrativeIR`；失败一律抛 `IRLoadError`。

    只做「读 + 解析 + 归一错误」，不做任何修补、不做任何默认值填充 ——
    读不出来就是读不出来，猜一份出来比报错更糟。
    """
    p = Path(path)
    if not p.is_file():
        raise IRLoadError(IRLoadError.MISSING, p, "不是文件或不存在")
    try:
        return NarrativeIR.from_json(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001  归一所有解析失败，理由见模块 docstring
        raise IRLoadError(IRLoadError.UNREADABLE, p, str(exc)) from exc
