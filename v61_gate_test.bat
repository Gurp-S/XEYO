@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem ============================================================================
rem  XEYO v61 GATE TEST  (docs/12 plan + docs/TODO completion gates + pre-launch notes)
rem
rem  HOW TO PROVIDE THE API KEY  (any one):
rem    1)  set DEEPSEEK_API_KEY=sk-xxxx   then run this script (same cmd window)
rem    2)  write the key to a one-line file  .diag_memory_cost\api.key   (recommended)
rem    3)  do nothing -- the script prompts you to paste it
rem
rem  Stages (G1 quality, G2 A1+A2 live hit-rate, G3 A3 daily monitor):
rem    G1  --ab new           : table A quality A/B (same-source, delta not worse by >5pp,
rem                             fact-layer no 0/3)
rem    G2  --hitrate-live     : A1 200+ round live tail-20 >= 99%; A2 extend-decouple
rem                             trans>=2 and tail-20 >= 98% and input < project input
rem    G3  --monitor-daily    : production 3-7 days daily hit >= 95% (needs production data)
rem    Summary: --gate-verdict  (offline), last line GATE_VERDICT=PASS|FAIL
rem
rem  Optional env vars:
rem    XEYO_REAL_SESSION_SRC   source for table A (default %USERPROFILE%\.xeyo\sessions\sess_real_200turn_c2.jsonl)
rem    XEYO_HITRATE_SESSION    long session for A1/A2 live (default = XEYO_REAL_SESSION; put a real 200+ turn session here)
rem    XEYO_GATE_STAGES        comma set ab,a1a2,a3 (default all; e.g. ab = quality only)
rem    XEYO_GATE_A2_RATIO      relax c2_extend_ratio rerun value for A2 (e.g. 0.1; default empty = skip)
rem    XEYO_HITRATE_BUDGET_CNY hit-rate cost guardrail in CNY (default 15)
rem ============================================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

rem ---- 0) KEY: env var > api.key file > interactive prompt ----
if defined DEEPSEEK_API_KEY goto :key_ok
if exist "%ROOT%.diag_memory_cost\api.key" set /p "DEEPSEEK_API_KEY=" < "%ROOT%.diag_memory_cost\api.key"
if defined DEEPSEEK_API_KEY goto :key_ok
set /p "DEEPSEEK_API_KEY=Paste your DEEPSEEK_API_KEY (Ctrl-C to abort): "
:key_ok
if "%DEEPSEEK_API_KEY%"=="" (echo [FAIL] missing DEEPSEEK_API_KEY & exit /b 1)
if "%DEEPSEEK_BASE_URL%"=="" set "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1"
if "%DEEPSEEK_MODEL%"=="" set "DEEPSEEK_MODEL=deepseek-v4-flash-vision-exp"
if "%XEYO_HITRATE_BUDGET_CNY%"=="" set "XEYO_HITRATE_BUDGET_CNY=15"

rem ---- 1) real source: copy into replay area (content fingerprint handles source change) ----
set "SRC=%XEYO_REAL_SESSION_SRC%"
if "%SRC%"=="" set "SRC=%USERPROFILE%\.xeyo\sessions\sess_real_200turn_c2.jsonl"
if not exist "%SRC%" (echo [FAIL] real session source missing: "%SRC%" & exit /b 1)
mkdir ".diag_memory_cost\replay" 2>nul
copy /y "%SRC%" ".diag_memory_cost\replay\replay.jsonl" >nul
set "XEYO_REAL_SESSION=%ROOT%.diag_memory_cost\replay\replay.jsonl"
if "%XEYO_HITRATE_SESSION%"=="" set "XEYO_HITRATE_SESSION=%XEYO_REAL_SESSION%"

rem ---- 2) isolated dirs (apply_sandbox overrides them again; kept for reconciliation) ----
set "XEYO_USAGE_DIR=%ROOT%.diag_memory_cost\usage_isolated"
set "XEYO_SESSIONS_DIR=%ROOT%.diag_memory_cost\sessions_isolated"
mkdir "%XEYO_USAGE_DIR%" 2>nul
mkdir "%XEYO_SESSIONS_DIR%" 2>nul

set "PYEXE=%ROOT%python\.venv\Scripts\python.exe"
set "EVAL=-m scripts.memory_stack_eval"

rem ---- 3) stage filter ----
set "STAGES=%XEYO_GATE_STAGES%"
if "%STAGES%"=="" set "STAGES=ab,a1a2,a3"
echo %STAGES% | findstr /i /c:"ab"   >nul && set "HAVEAB=1"
echo %STAGES% | findstr /i /c:"a1a2" >nul && set "HAVEA12=1"
echo %STAGES% | findstr /i /c:"a3"   >nul && set "HAVEA3=1"

pushd "%ROOT%python"

rem ================= G0: verdict on existing evidence =================
echo.
echo [G0] verdict on existing evidence (offline, free):
echo      tableA source : %XEYO_REAL_SESSION%
echo      A1/A2 source  : %XEYO_HITRATE_SESSION%
"%PYEXE%" %EVAL% --gate-verdict

if defined HAVEAB (
  echo.
  echo [G1/%STAGES%] table A quality A/B --ab new  (same-source real+synth; 240tok/question; temp=0; x3)
  echo       cost approx 0.5-3 CNY. Source change re-measures project baseline automatically.
  echo       (per-shot prints hit%% / CNY-per-shot / cumulative CNY)
  "%PYEXE%" %EVAL% --ab new
  if errorlevel 1 echo [WARN] --ab new exited non-zero; check output above
)

if defined HAVEA12 (
  echo.
  echo [G2/%STAGES%] A1+A2 live hit-rate (ultra band = whole session; project+c2 both arms)
  echo       source: %XEYO_HITRATE_SESSION%
  echo       cost ~ a few CNY (guardrail budget %XEYO_HITRATE_BUDGET_CNY% CNY, stops when exceeded).
  echo       pass: A1 c2 tail-20 gt/eq 99 pct ; A2 trans gt/eq 2 and tail-20 gt/eq 98 pct and input < project.
  set "XEYO_HITRATE_BANDS=ultra"
  set "XEYO_HITRATE_MODES=project,c2"
  set "XEYO_HITRATE_MAX_SHOTS=440"
  "%PYEXE%" %EVAL% --hitrate-live
  if errorlevel 1 echo [WARN] --hitrate-live exited non-zero; check output above

  if not "%XEYO_GATE_A2_RATIO%"=="" if not "%XEYO_GATE_A2_RATIO%"=="0" (
    echo.
    echo [G2b] A2 relax rerun: c2_extend_ratio=%XEYO_GATE_A2_RATIO%  (tag=a2r; restore overlay after)
    "%PYEXE%" -c "import shutil,pathlib; p=pathlib.Path('memory/simulator/params_overlay.json'); b=p.parent/'params_overlay.json.bak'; shutil.copy2(p,b) if p.exists() else None; print('overlay backed up' if p.exists() else 'no overlay')"
    "%PYEXE%" -c "from memory.simulator.params import write_overlay; write_overlay({'c2_extend_ratio': float(%XEYO_GATE_A2_RATIO%)}); print('overlay c2_extend_ratio ->', %XEYO_GATE_A2_RATIO%)"
    set "XEYO_HITRATE_TAG=a2r"
    set "XEYO_HITRATE_MODES=c2"
    set "XEYO_HITRATE_MAX_SHOTS=220"
    "%PYEXE%" %EVAL% --hitrate-live
    if errorlevel 1 echo [WARN] A2b exited non-zero
    "%PYEXE%" -c "import shutil,pathlib; p=pathlib.Path('memory/simulator/params_overlay.json'); b=p.parent/'params_overlay.json.bak'; shutil.copy2(b,p) if b.exists() else None; b.unlink(missing_ok=True); print('overlay restored')"
    set "XEYO_HITRATE_TAG="
  )
)

if defined HAVEA3 (
  echo.
  echo [G3/%STAGES%] daily monitor snapshot (reads production ledger; needs 3-7 days, skip if none)
  set "XEYO_USAGE_DIR="
  "%PYEXE%" %EVAL% --monitor-daily
  if errorlevel 1 echo [NOTE] no production ledger for today; A3 needs daily collection (verdict reports as not met)
)

echo.
echo ================= FINAL VERDICT =================
"%PYEXE%" %EVAL% --gate-verdict
set "GVC=%errorlevel%"
popd
if "%GVC%"=="0" (
  echo.
  echo [RESULT] PASS --- all gates green: enable per docs/12 form (XEYO_C2_GATE=1 gray for long sessions; run A3 full before production default)
) else (
  echo.
  echo [RESULT] FAIL --- not meeting acceptance; v61 allowed only as experimental channel (test/A-B/reconciliation), not production.
)
exit /b %GVC%
