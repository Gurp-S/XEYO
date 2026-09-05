@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem ============================================================================
rem  LoCoMo-Refined -> XEYO one-shot eval
rem
rem  HOW TO PROVIDE THE API KEY (any one):
rem    1) set DEEPSEEK_API_KEY=sk-xxxx then run this script (same cmd window)
rem    2)  write the key to a one-line file  .diag_memory_cost\api.key  (recommended)
rem    3) do nothing -- the script prompts you to paste it
rem
rem  HOW TO PROVIDE THE LOCOMO DATA:
rem    1) set XEYO_LOCOMO_DATA=<path to locomo jsonl> (or)
rem    2) place the file at .diag_memory_cost\locomo\locomo_data.jsonl
rem
rem  Stages:
rem    S1 convert : LoCoMo jsonl -> XEYO session jsonl + carrier.jsonl (offline, free)
rem    S2 health  : --source-health on the chosen carrier (A6 gate, offline, free)
rem    S3 hitrate : --hitrate-live project vs c2 (live, budget-guarded)
rem    S3r report : cost / hit-rate summary (offline, free)
rem    S4 verdict : --gate-verdict summary (offline, free)
rem
rem  Optional env vars:
rem    XEYO_HITRATE_BANDS   ultra,long,medium (default ultra)
rem    XEYO_HITRATE_MODES   project,c2 (default both)
rem    XEYO_HITRATE_BUDGET_CNY  live cost guardrail in CNY (default 15)
rem    XEYO_HITRATE_MAX_SHOTS   max shots (default 440)
rem
rem  NOTE: LoCoMo is pure chat (no tools). The A6 source-health gate would
rem        reject it for tool_result<20. This script therefore sets
rem        XEYO_ALLOW_UNHEALTHY_SOURCE=1 so the memory hit-rate run may proceed.
rem        (Real tool sessions keep the strict gate.)
rem ============================================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

rem ---- 0) KEY: env var > api.key file > interactive prompt ----
if defined DEEPSEEK_API_KEY goto :key_ok
if exist "%ROOT%.diag_memory_cost\api.key" set /p "DEEPSEEK_API_KEY=" < "%ROOT%.diag_memory_cost\api.key"
if defined DEEPSEEK_API_KEY goto :key_ok
set /p "DEEPSEEK_API_KEY=Paste your DEEPSEEK_API_KEY (Ctrl-C to abort): "
:key_ok
if "%DEEPSEEK_API_KEY%"=="" (echo [FAIL] missing DEEPSEEK_API_KEY & pause & exit /b 1)
if "%DEEPSEEK_BASE_URL%"=="" set "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1"
if "%DEEPSEEK_MODEL%"=="" set "DEEPSEEK_MODEL=deepseek-v4-flash-vision-exp"
if "%XEYO_HITRATE_BUDGET_CNY%"=="" set "XEYO_HITRATE_BUDGET_CNY=15"

rem ---- 1) locomo data: env var > default path ----
set "DATA=%XEYO_LOCOMO_DATA%"
if "%DATA%"=="" set "DATA=%ROOT%.diag_memory_cost\locomo\locomo_data.jsonl"
if not exist "%DATA%" (echo [FAIL] LoCoMo data missing: "%DATA%" & echo        set XEYO_LOCOMO_DATA or place at .diag_memory_cost\locomo\locomo_data.jsonl & pause & exit /b 1)

rem ---- 2) isolated run dirs ----
set "XEYO_USAGE_DIR=%ROOT%.diag_memory_cost\usage_isolated"
set "XEYO_SESSIONS_DIR=%ROOT%.diag_memory_cost\sessions_isolated"
mkdir "%XEYO_USAGE_DIR%" 2>nul
mkdir "%XEYO_SESSIONS_DIR%" 2>nul

set "PYEXE=%ROOT%python\.venv\Scripts\python.exe"
set "EVAL=-m scripts.memory_stack_eval"
rem [fix 2026-09-04] eval modules live under python/, -m needs cwd=python
rem (all other paths are %ROOT%-anchored absolute; cwd change is safe)
cd /d "%ROOT%python"

rem ================= S1: convert (offline, free) =================
echo.
call :ask S1/4
if errorlevel 1 exit /b 1
echo [run] S1/4 LoCoMo -^> XEYO session jsonl + carrier (offline, free)
"%PYEXE%" -m scripts.locomo_convert --input "%DATA%" --outdir "%ROOT%.diag_memory_cost\locomo\out" --min-rows 200
if errorlevel 1 echo [WARN] S1 convert exited non-zero; check above

set "CARRIER=%ROOT%.diag_memory_cost\locomo\out\carrier.jsonl"
if not exist "%CARRIER%" (echo [FAIL] carrier not generated: "%CARRIER%" & pause & exit /b 1)
echo [done] S1/4 carrier: %CARRIER%

rem ================= S2: source health (offline, free) =================
echo.
call :ask S2/4
if errorlevel 1 exit /b 1
echo [run] S2/4 A6 source-health on carrier (offline, free)
"%PYEXE%" %EVAL% --source-health "%CARRIER%"
echo [done] S2/4

rem ================= S3: hitrate-live (live, guarded) =================
echo.
call :ask S3/4
if errorlevel 1 exit /b 1
echo [run] S3/4 --hitrate-live project vs c2 (live; budget guardrail %XEYO_HITRATE_BUDGET_CNY% CNY)
set "XEYO_REAL_SESSION=%CARRIER%"
set "XEYO_HITRATE_SESSION=%CARRIER%"
if "%XEYO_HITRATE_BANDS%"=="" set "XEYO_HITRATE_BANDS=ultra"
if "%XEYO_HITRATE_MODES%"=="" set "XEYO_HITRATE_MODES=project,c2"
if "%XEYO_HITRATE_MAX_SHOTS%"=="" set "XEYO_HITRATE_MAX_SHOTS=440"
rem LoCoMo chat-only: bypass A6 hard-gate for the memory run (real tool sessions keep the strict gate)
set "XEYO_ALLOW_UNHEALTHY_SOURCE=1"
set "XEYO_HITRATE_TAG=locomo"
"%PYEXE%" %EVAL% --hitrate-live
if errorlevel 1 echo [WARN] S3 hitrate-live exited non-zero; check above
set "XEYO_HITRATE_TAG="
rem keep XEYO_ALLOW_UNHEALTHY_SOURCE=1 through S4: chat-only source is
rem the intended premise for LoCoMo; S4 is an offline read-only verdict.
echo [done] S3/4 hitrate-live finished

rem ================= S3r: report (offline, free) =================
echo.
call :ask S3r/4
if errorlevel 1 exit /b 1
echo [run] S3r/4 cost / hit-rate summary (offline, free)
"%PYEXE%" -m scripts.locomo_report --usage "%XEYO_USAGE_DIR%" --quality "%ROOT%python\memory\simulator\out\quality_validation.json"
echo [done] S3r/4

rem ================= S4: verdict (offline, free) =================
echo.
call :ask S4/4
if errorlevel 1 exit /b 1
echo [run] S4/4 GATE VERDICT (offline, free)
"%PYEXE%" %EVAL% --gate-verdict
set "GVC=%errorlevel%"

echo.
if "%GVC%"=="0" (
  echo [RESULT] PASS --- gates green per docs/12
) else (
  echo [RESULT] FAIL --- check missing items above; v61 stays experimental channel
)
exit /b %GVC%

rem ================= :ask ??? =================
:ask
set "ANS="
set /p "ANS=Continue %~1? (y/n): "
if /i "%ANS%"=="y" exit /b 0
echo [skip] %~1 cancelled
echo.
exit /b 1
