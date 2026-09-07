<#
.SYNOPSIS
    构建 XEYO 开箱即用桌面安装包（NSIS + MSI）。

.DESCRIPTION
    1. 精简 Python 代码（去掉 evals/bridge/scripts/tests/_shadow）到 gui/src-tauri/resources/python/
    2. 复制并精简 .venv（去 .pyc/.pyd/cache/文档；裁掉 ray/sqlalchemy/pytest/playwright）
    3. 在精简 venv 内补装 typer（cli.config_store 所需）
    4. 配 tauri.conf.json 把 resources 指向精简 python（已就位）
    5. 运行 npm run tauri:build（生成 NSIS + MSI installer）

    产物：gui/src-tauri/target/release/bundle/{nsis,msi}/
    安装后大小：~200M（含精简 Python 引擎 ~40M + 代码 ~4M + 前端 + GUI 壳）

.NOTES
    - 前提：rust 已装（cargo 1.97+）、node 20+、python 3.11+ 在 PATH
    - NSIS 由 tauri-bundler 首次自动下载（~5MB）
    - 若已 resources/python 已存在且通过验证，可跳过步骤 1-3
#>

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==[XEYO 安装包构建]=="

# 1) 精简 Python 代码
if (-not (Test-Path "gui/src-tauri/resources/python/server") -or $env:FORCE_SLIM -eq "1") {
    Write-Host "`n== 1/4 精简 Python 代码 =="
    & python scripts/build_slim_python.py
} else {
    Write-Host "`n== 1/4 跳过(已精简)=="
}

# 2) 复制精简 venv（包含 .venv 准备脚本）
if (-not (Test-Path "gui/src-tauri/resources/python/.venv/Scripts/python.exe")) {
    Write-Host "`n== 2/4 复制精简 venv =="
    & python scripts/build_slim_venv.py
} else {
    Write-Host "`n== 2/4 跳过(已存在)=="
}

# 3) 补装缺失依赖（typer 等）
Write-Host "`n== 3/4 补装 typer =="
& "gui/src-tauri/resources/python/.venv/Scripts/python.exe" -m pip install typer 2>&1 | Out-Null

# 4) 验证精简环境可启动
Write-Host "`n== 4/4 验证精简环境 =="
& "gui/src-tauri/resources/python/.venv/Scripts/python.exe" -c "import fastapi, uvicorn, httpx, typer, playwright, mss, PIL, multipart; print('runtime deps OK')"

# 5) 打包 Tauri
Write-Host "`n== Tauri 构建 =="
Set-Location gui
& npm install 2>&1 | Out-Null
& npm run tauri:build

Write-Host "`n==完成=="
Write-Host "NSIS: gui/src-tauri/target/release/bundle/nsis/XEYO_0.1.0_x64-setup.exe"
Write-Host "MSI:  gui/src-tauri/target/release/bundle/msi/XEYO_0.1.0_x64_en-US.msi"