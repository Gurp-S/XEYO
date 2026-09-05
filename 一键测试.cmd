@echo off
title XEYO one-click tests
cd /d "%~dp0"

echo ============================================
echo  XEYO one-click tests
echo  (gui typecheck + gui vitest + python pytest)
echo ============================================
echo.

where pnpm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pnpm not found in PATH. Run inside a shell with pnpm available.
    pause
    exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] py launcher not found in PATH. Need Python 3.11.
    pause
    exit /b 1
)

echo ===== [1/3] GUI typecheck =====
pushd gui
call pnpm typecheck
set GUI_TC=%ERRORLEVEL%
popd
echo.

echo ===== [2/3] GUI vitest (full suite, 1-3 min) =====
pushd gui
call pnpm test
set GUI_VT=%ERRORLEVEL%
popd
echo.

echo ===== [3/3] Python pytest (memory/session suites) =====
pushd python
set PYTHONPATH=.
set PYTHONIOENCODING=utf-8
py -3.11 -m pytest tests\test_memory_search.py tests\test_memory_tool.py tests\test_session_presence.py tests\test_memdir.py tests\test_cross_session_memory.py tests\test_agent_scope.py tests\test_nightshift.py tests\test_session_md.py -q
set PY_T=%ERRORLEVEL%
popd

echo.
echo ================= SUMMARY =================
echo  GUI typecheck : %GUI_TC%   (0 = pass)
echo  GUI vitest    : %GUI_VT%   (0 = pass)
echo  Python pytest : %PY_T%   (0 = pass)
echo ============================================
echo  All zeros = all pass. If any FAIL, send this window output to the AI.
echo.
pause
