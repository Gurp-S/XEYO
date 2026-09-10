<#
.SYNOPSIS
    构建 XEYO 开箱即用桌面安装包（NSIS + MSI）。

.DESCRIPTION
    1. 精简 Python 代码（去掉 evals/bridge/scripts/tests/_shadow）到 gui/src-tauri/resources/python/
    2. 构建**自包含** Python 运行时到 resources/python/.venv（见下方"为什么要自包含"）
    3. 配 tauri.conf.json 把 resources 指向精简 python（已就位）
    4. 运行 npm run tauri:build（生成 NSIS + MSI installer）

    产物：gui/src-tauri/target/release/bundle/{nsis,msi}/

    为什么要自包含（历史事故，2026-09-10）：
    以前这一步是"复制项目 .venv"，而 virtualenv/venv 产出的都是**薄壳**——
    Scripts/python.exe 只是 ~270KB launcher，真正的 python3xx.dll 与标准库
    留在构建机的 base 解释器（pyvenv.cfg 的 home= 指向
    C:\Users\<someone>\AppData\Local\...）。发布包装到没装该版本 Python 的机器
    上时，文件俱在但 python.exe 启动即失败；Tauri 壳只把错误写进 stderr，
    界面统一显示"无法连接后端"，用户误以为是端口/网络问题。
    现在改用 python-build-standalone 的可重定位 CPython：自带 DLL + 标准库，
    解压即用，不依赖目标机装 Python。

.NOTES
    - 前提：rust 已装（cargo 1.97+）、node 20+、python 3.11+ 在 PATH
      （构建机需要 Python 仅用于跑构建脚本；产物本身不依赖它）
    - NSIS 由 tauri-bundler 首次自动下载（~5MB）
    - 需要联网：首次会下载 ~46MB 的 CPython 发行包到 .cache/（之后走缓存）
    - 逐步骤验证由 build_slim_venv.py 自己做（含自包含性断言），这里不重复
    - FORCE_SLIM=1 强制重建已就位的产物
#>

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$VenvPy = "gui/src-tauri/resources/python/.venv/python.exe"

Write-Host "==[XEYO 安装包构建]=="

# 1) 精简 Python 代码
if (-not (Test-Path "gui/src-tauri/resources/python/server") -or $env:FORCE_SLIM -eq "1") {
    Write-Host "`n== 1/3 精简 Python 代码 =="
    & python scripts/build_slim_python.py
} else {
    Write-Host "`n== 1/3 跳过(已精简) =="
}

# 2) 构建自包含运行时（下载 CPython + 装依赖 + 自包含性断言）
if (-not (Test-Path $VenvPy) -or $env:FORCE_SLIM -eq "1") {
    Write-Host "`n== 2/3 构建自包含 Python 运行时 =="
    & python scripts/build_slim_venv.py
} else {
    Write-Host "`n== 2/3 跳过(已存在) =="
    & $VenvPy -c "import fastapi, uvicorn, httpx, typer, rich, playwright, mss, PIL, multipart; print('runtime deps OK')"
}

# 3) 打包 Tauri
Write-Host "`n== 3/3 Tauri 构建 =="
Set-Location gui
& npm install 2>&1 | Out-Null
& npm run tauri:build

Write-Host "`n==完成=="
Write-Host "NSIS: gui/src-tauri/target/release/bundle/nsis/XEYO_0.1.0_x64-setup.exe"
Write-Host "MSI:  gui/src-tauri/target/release/bundle/msi/XEYO_0.1.0_x64_en-US.msi"
