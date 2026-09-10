#!/usr/bin/env bash
# XEYO 安装包构建脚本（Linux/macOS 同流程；产物为当前平台 tauri 格式，非 NSIS/MSI）
#
# 与 build_installer.ps1 的差异：build_slim_venv.py 目前只下载 Windows 的
# python-build-standalone 发行包。非 Windows 平台需要先为本平台准备自包含
# 解释器（同样的可重定位要求），否则产物会退回"薄壳 venv"的老问题。
set -euo pipefail
cd "$(dirname "$0")/.."

VENV_PY="gui/src-tauri/resources/python/.venv/bin/python"

echo "==[XEYO 安装包构建]=="

# 1) 精简 Python 代码
if [[ ! -d gui/src-tauri/resources/python/server || "${FORCE_SLIM:-}" == "1" ]]; then
    echo -e "\n== 1/3 精简 Python 代码 =="
    python3 scripts/build_slim_python.py
else
    echo -e "\n== 1/3 跳过(已精简) =="
fi

# 2) 构建自包含运行时（含自包含性断言；构建脚本目前面向 Windows 资产）
if [[ ! -f "$VENV_PY" || "${FORCE_SLIM:-}" == "1" ]]; then
    echo -e "\n== 2/3 构建自包含 Python 运行时 =="
    python3 scripts/build_slim_venv.py
else
    echo -e "\n== 2/3 跳过(已存在) =="
    "$VENV_PY" -c "import fastapi, uvicorn, httpx, typer, rich, playwright, mss, PIL, multipart; print('runtime deps OK')"
fi

# 3) Tauri build
echo -e "\n== 3/3 Tauri 构建 =="
cd gui
npm install
npm run tauri:build
