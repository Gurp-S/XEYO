@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem ============================================================================
rem  XEYO A3 DAILY MONITOR  (docs/12 C4 + TODO A3 completion gate)
rem
rem  WHAT: once a day, read PRODUCTION ledger (~/.xeyo/usage) and write a
rem        snapshot row (deploy_project_mode_<day>) into docs/12 table D,
rem        then print the offline gate verdict.
rem  GATE: daily hit-rate >= 95% AND C2 count controlled (off = 0; gray = bounded).
rem        3-7 consecutive qualifying days => A3 gate green.
rem  SCHEDULE: register as a daily task, see docs/A3-monitor-and-c2-gray.md.
rem  NOTE: do NOT set XEYO_C2_GATE / XEYO_USAGE_DIR here (must read the real ledger).
rem        This bat is independent of v61_gate_test.bat (which uses isolated dirs).
rem ============================================================================
set "ROOT=%~dp0"
set "PYEXE=%ROOT%python\.venv\Scripts\python.exe"
set "EVAL=-m scripts.memory_stack_eval"
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "DAY=%%d"
set "LDIR=%ROOT%.diag_memory_cost\a3"
if not exist "%LDIR%" mkdir "%LDIR%"
set "LOG=%LDIR%\a3_%DAY%.log"
rem  verdict needs the table-A source fingerprint; point it at the replay if present,
rem  otherwise the verdict honestly marks table-A as "not current source".
if exist "%ROOT%.diag_memory_cost\replay\replay.jsonl" set "XEYO_REAL_SESSION=%ROOT%.diag_memory_cost\replay\replay.jsonl"

pushd "%ROOT%python"
echo ===== A3 snapshot %date% %time% ===== >> "%LOG%"
"%PYEXE%" -X utf8 %EVAL% --monitor-daily >> "%LOG%" 2>&1
"%PYEXE%" -X utf8 %EVAL% --gate-verdict >> "%LOG%" 2>&1
echo.
echo [A3] snapshot done. Log: %LOG%
echo [A3] gate verdict (offline, free):
"%PYEXE%" -X utf8 %EVAL% --gate-verdict
popd
exit /b 0
