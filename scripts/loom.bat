@echo off
setlocal

rem ---------------------------------------------------------------------------
rem Loom 零配置启动器 (Windows)。
rem 双击 scripts\loom.bat 即可使用，无需懂 python / venv。
rem 逻辑：优先用项目自带的 .venv\Scripts\python.exe；没有就找系统 python3/python；
rem 都没有可用的（含依赖）就尝试自动建 .venv 并 pip 安装；失败（如没网）只打印
rem 人话提示 + 下一步精确命令，绝不抛 Python traceback。
rem ---------------------------------------------------------------------------

set "SCRIPT_DIR=%~dp0"
rem 本文件位于 <项目>/scripts/，项目根目录是其父目录。
set "ROOT=%SCRIPT_DIR%.."
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "REQ=%ROOT%\requirements.txt"

rem 切到项目根目录，这样 `python -m loom` 才能找到 loom 包。
cd /d "%ROOT%" || (
    echo Loom: 无法进入项目目录 "%ROOT%" >&2
    exit /b 2
)

set "PY="

rem 1) 优先使用项目自带的虚拟环境。
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
    goto :launch
)

rem 2) 否则找一个已装好 loom + pydantic 的系统 python。
where python3 >nul 2>nul && set "PY=python3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if defined PY (
    "%PY%" -c "import loom, pydantic" >nul 2>nul
    if not errorlevel 1 (
        goto :launch
    )
)

rem 3) 没有可用 python -> 尝试创建本地 .venv 并安装依赖。
echo.
echo Loom: 没有可用的 Python 环境，正在尝试创建本地 .venv 并安装依赖...
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo 未检测到 Python。请先安装 Python 3.10+ 再运行本脚本。
    echo 下载: https://www.python.org/downloads/
    echo 然后手动执行:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo     scripts\loom.bat
    exit /b 2
)

python -m venv "%ROOT%\.venv" 2>nul
if not exist "%VENV_PY%" (
    echo 创建虚拟环境失败（可能缺少 venv 模块或权限不足）。
    echo 请手动执行:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 2
)

"%VENV_PY%" -m pip install -r "%REQ%" 2>nul
if errorlevel 1 (
    echo.
    echo 依赖安装失败（多半是没有网络或无法访问 PyPI）。
    echo 请联网后手动执行:
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo 然后再次运行 scripts\loom.bat
    exit /b 2
)

set "PY=%VENV_PY%"

:launch
rem 双击且没给子命令 -> 直接打开网页界面（最省事、最有用）。
if "%~1"=="" (
    "%PY%" -m loom web
) else (
    "%PY%" -m loom %*
)
goto :eof
