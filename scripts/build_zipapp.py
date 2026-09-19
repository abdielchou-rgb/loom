#!/usr/bin/env python3
"""Build a single-file `keel.pyz` executable archive using stdlib `zipapp`.

    python scripts/build_zipapp.py     # 生成 ./keel.pyz
    python keel.pyz --help
    python keel.pyz web

This bundles the `keel/` package together with a tiny console shim that
dispatches argv to `keel.cli:main`, producing one portable file.

PREREQUISITE (documented, NOT bundled):
    `pydantic` is a hard runtime dependency and cannot be auto-bundled by
    stdlib zipapp without vendoring it ourselves (out of scope and would add a
    dependency-bundling step). The shim therefore imports pydantic from the
    host Python. If it is missing, you get ONE LINE of setup guidance instead
    of a traceback:

        Keel 需要 pydantic：请先 `pip install pydantic`
        （或直接使用 scripts/keel.bat / scripts/keel.sh 自动配置）。

If you want a truly zero-setup artifact, use scripts/keel.bat (Windows) or
scripts/keel.sh (POSIX) instead -- those create/activate the venv for you.
"""

from __future__ import annotations

import shutil
import sys
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEL_PKG = ROOT / "keel"
OUT = ROOT / "keel.pyz"

# Console shim placed at the top level of the archive; `main` is the zipapp
# entry point. It checks for pydantic first so a missing dep yields a friendly
# one-liner rather than an ImportError traceback to the user.
SHIM = '''\
import sys


def main():
    try:
        import pydantic  # noqa: F401  hard dependency, must come from host
    except ImportError:
        sys.stderr.write(
            "Keel 需要 pydantic：请先 `pip install pydantic` "
            "（或直接使用 scripts/keel.bat / scripts/keel.sh 自动配置）。\\n"
        )
        return 2
    from keel.cli import main as keel_main

    return keel_main()


if __name__ == "__main__":
    sys.exit(main())
'''


def main() -> int:
    if not KEEL_PKG.is_dir():
        print(f"找不到 keel 包目录：{KEEL_PKG}", file=sys.stderr)
        return 2

    build_dir = ROOT / "_build_pyz"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    pkg_dest = build_dir / "keel"
    shutil.copytree(KEEL_PKG, pkg_dest)
    (build_dir / "_keel_shim.py").write_text(SHIM, encoding="utf-8")

    try:
        zipapp.create_archive(
            source=build_dir,
            target=OUT,
            main="_keel_shim:main",
            compressed=True,
        )
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)

    print(f"已生成 {OUT} （{OUT.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
