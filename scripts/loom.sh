#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Loom 零配置启动器 (POSIX / Linux / macOS)。
# 用法:  ./scripts/loom.sh            # 双击/无参数 -> 打开网页界面
#        ./scripts/loom.sh --help
#        ./scripts/loom.sh audit out/xxx/ir.json
#
# 逻辑: 优先用项目自带的 .venv/bin/python；没有就找系统 python3/python；
# 都没有可用的（含依赖）就尝试自动建 .venv 并 pip 安装；失败（如没网）只打印
# 人话提示 + 下一步精确命令，绝不抛 Python traceback。
# ---------------------------------------------------------------------------
set -u

# 本文件位于 <项目>/scripts/，项目根目录是其父目录。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$ROOT/.venv/bin/python"
REQ="$ROOT/requirements.txt"

# 切到项目根目录，这样 `python -m loom` 才能找到 loom 包。
cd "$ROOT" || { echo "Loom: 无法进入项目目录 $ROOT" >&2; exit 2; }

PY=""

# 1) 优先使用项目自带的虚拟环境。
if [ -x "$VENV_PY" ]; then
    PY="$VENV_PY"
# 2) 否则找一个已装好 loom + pydantic 的系统 python。
elif PYBIN="$(command -v python3 || command -v python)"; then
    if "$PYBIN" -c "import loom, pydantic" >/dev/null 2>&1; then
        PY="$PYBIN"
    fi
fi

# 3) 没有可用 python -> 尝试创建本地 .venv 并安装依赖。
if [ -z "$PY" ]; then
    echo ""
    echo "Loom: 没有可用的 Python 环境，正在尝试创建本地 .venv 并安装依赖..."
    echo ""

    PYBIN="$(command -v python3 || command -v python || true)"
    if [ -z "$PYBIN" ]; then
        echo "未检测到 Python。请先安装 Python 3.10+ 再运行本脚本。"
        echo "下载: https://www.python.org/downloads/"
        echo "然后手动执行:"
        echo "    python3 -m venv .venv"
        echo "    .venv/bin/python -m pip install -r requirements.txt"
        echo "    scripts/loom.sh"
        exit 2
    fi

    if ! "$PYBIN" -m venv "$ROOT/.venv" 2>/dev/null; then
        echo "创建虚拟环境失败（可能缺少 venv 模块或权限不足）。"
        echo "请手动执行:"
        echo "    python3 -m venv .venv"
        echo "    .venv/bin/python -m pip install -r requirements.txt"
        exit 2
    fi

    if ! "$VENV_PY" -m pip install -r "$REQ" 2>/dev/null; then
        echo ""
        echo "依赖安装失败（多半是没有网络或无法访问 PyPI）。"
        echo "请联网后手动执行:"
        echo "    .venv/bin/python -m pip install -r requirements.txt"
        echo "然后再次运行 scripts/loom.sh"
        exit 2
    fi

    PY="$VENV_PY"
fi

# 双击且没给子命令 -> 直接打开网页界面（最省事、最有用）。
if [ "$#" -eq 0 ]; then
    "$PY" -m loom web
else
    "$PY" -m loom "$@"
fi
