@echo off
REM ================================================================
REM  XEYO 记忆系统离线评估（v61 decide / aging / C2 质量）
REM  离线 = 不调任何 API = 0 元。只跑 simulator 与质量/成本分档。
REM
REM  用法（在仓库根双击，或 cmd 里运行）：
REM    run-memory-eval.bat                  -> 离线战役（默认，0 元）
REM    run-memory-eval.bat --hitrate-live   -> 在线命中率/成本实测（花钱）
REM
REM  在线需先设 key（脚本读环境变量，不写进文件；key 在你的 docs\key.txt）：
REM    set DEEPSEEK_API_KEY=<粘贴>
REM  在线安全护栏（可选，设了就自动停）：
REM    set XEYO_HITRATE_MAX_SHOTS=40        （最多打多少枪，到就停）
REM    set XEYO_HITRATE_BUDGET_CNY=3        （累计成本到 3 元就停）
REM    set XEYO_HITRATE_MODES=project       （只跑 project，跳过会断链的 c2）[实现见下]
REM  价格（flash 空闲）：hit 0.05 / miss 1.5 / out 4.5 元每百万token
REM  进度：--hitrate-live 会逐枪打印 prompt/hit/miss/rate/本枪¥/累计¥；随时 Ctrl-C 即停(只结算已跑枪)。
REM ================================================================
setlocal
cd /d "%~dp0"

REM ---- 绝对路径，避免拼接出错 ----
set "PY=%~dp0python\.venv\Scripts\python.exe"
set "PYSRC=%~dp0python"
set "PYTHONPATH=%PYSRC%"
if not defined XEYO_USAGE_DIR    set "XEYO_USAGE_DIR=%~dp0.diag_memory_cost\usage_isolated"
if not defined XEYO_SESSIONS_DIR set "XEYO_SESSIONS_DIR=%~dp0.diag_memory_cost\sessions_isolated"

if not exist "%PY%" (
  echo [错误] 没找到 venv Python: %PY%
  echo        先运行  cd python ^&^& py -3.11 -m pip install -r requirements.txt 建依赖
  pause
  exit /b 1
)

echo.
echo  [命令行] %*
echo  [隔离目录] %XEYO_USAGE_DIR%
echo  [开始] 离线 formula 战役 + 质量验证（v61 decide / aging / C2，0 元）...
echo.
pushd "%PYSRC%"
"%PY%" scripts\memory_stack_eval.py %*
set "RC=%ERRORLEVEL%"
popd

echo.
echo  [退出码 %RC%]
echo  报告位置：
echo    %~dp0python\scripts\out\memory_stack_eval.json      (机器可读)
echo    %~dp0python\scripts\out\memory_stack_eval.md        (人读)
echo    %~dp0python\scripts\out\quality_validation.json     (质量/成本分档)
echo.
echo  想让窗口停留便于查看：本窗口已 pause。
pause
endlocal
