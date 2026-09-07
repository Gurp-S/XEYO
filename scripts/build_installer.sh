#!/usr/bin/env bash
# XEYO 安装包构建脚本（Linux/macOS 同流程；产物为当前平台 tauri 格式，非 NSIS/MSI）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==[XEYO 安装包构建]=="

# 1) 精简 Python 代码
if [[ ! -d gui/src-tauri/resources/python/server || "${FORCE_SLIM:-}" == "1" ]]; then
    echo -e "\n== 1/4 精简 Python 代码 =="
    python3 scripts/build_slim_python.py
else
    echo -e "\n== 1/4 跳过(已精简)=="
fi

# 2) 精简 venv
if [[ ! -f gui/src-tauri/resources/python/.venv/bin/python ]]; then
    echo -e "\n== 2/4 复制精简 venv =="
    python3 scripts/build_slim_venv.py
else
    echo -e "\n== 2/4 跳过(已存在)=="
fi

# 3) 补装 typer
echo -e "\n== 3/4 补装 typer =="
gui/src-tauri/resources/python/.venv/bin/python -m pip install typer >/dev/null

# 4) 验证
echo -e "\n== 4/4 验证精简环境 =="
gui/src-tauri/resources/python/.venv/bin/python -c "import fastapi, uvicorn, httpx, typer, playwright, mss, PIL, multipart; print('runtime deps OK')"

# 5) Tauri build
echo -e "\n== Tauri 构建 =="
cd gui
npm install
npm run tauri:build