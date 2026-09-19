"""IR 模型基类。

**为什么单独一个文件**：`models.py` 是三层正交模型的容器，它现在需要引用
`tom.py`（信念层）与 `proposal.py`（提案层）的类型。如果基类还留在 `models.py`，
那三个文件就会互相 import 成环：

    models.py -> tom.py -> models.py   # 环

把基类下沉到 `base.py`，依赖就变成单向的：

    base.py  <-  models.py
    base.py  <-  tom.py
    base.py  <-  proposal.py

这是「跨层共用的概念上移到 IR 层」那条铁律的一个变体：
**共用的基类要下沉到被共用者之下**，否则每加一个 IR 子模块都要绕开这个环。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KeelModel(BaseModel):
    """所有 IR 模型的基类：禁止未知字段，保证 schema 是硬契约。

    `extra="forbid"` 不是洁癖 —— schema 是 IR 与 renderer / 校验器 / 提示词
    之间的接口契约。允许未知字段意味着「拼错字段名」会静默变成「少了一个约束」。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


__all__ = ["KeelModel"]
