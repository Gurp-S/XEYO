@echo off
rem ============================================================
rem  T_now shape preview (read-only): renders 3 scenarios
rem  (D1 vague-turn gating / A1 placement + B2 windowing /
rem   after_tools legacy contract). Double-click to run.
rem ============================================================
setlocal
set ROOT=%~dp0
chcp 65001 >nul

echo ======== T_now shape preview (3 scenarios) ========
pushd "%ROOT%python"
py -3.11 scripts\preview_t_now.py
set RC=%ERRORLEVEL%
popd

echo.
echo preview exit code: %RC%
echo (close this window when done)
pause
exit /b %RC%
