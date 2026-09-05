@echo off
rem ============================================================
rem  Peer topics toolization one-click checks (push -> pull).
rem  Double-click to run. No server / engine needed.
rem  Read-only + pytest subset.
rem ============================================================
setlocal
set ROOT=%~dp0
chcp 65001 >nul

echo ======== pytest subset (peer presence / cross-session memory / memory tool) ========
pushd "%ROOT%python"
py -3.11 -m pytest tests\test_session_presence.py tests\test_cross_session_memory.py tests\test_memory_tool.py tests\test_multi_agent_p0.py -q
set RC=%ERRORLEVEL%
popd

echo.
echo pytest exit code: %RC%
echo (close this window when done)
pause
exit /b %RC%
