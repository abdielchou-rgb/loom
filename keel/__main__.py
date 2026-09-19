"""允许 `python -m keel` 直接运行。

装了包之后更推荐用 `keel` 命令（console script，见 pyproject.toml）；
这一层是给「不想装、只想跑」的场景用的 ——
**门槛决定采用**（InkOS 因本地部署 + 命令行在中文横评里只排第 8），
每少一步操作，就多一个人能真正用上。
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
