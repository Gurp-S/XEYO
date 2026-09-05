@echo off
REM =====================================================================
REM XEYO P0/P1 baseline - one-click full pytest (285+)
REM MUST use Python 3.11  (default python here is 3.14)
REM Result log: D:\lea\XenYon code\logs\pytest-baseline.log
REM Window stays open at the end (press any key to close).
REM =====================================================================
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
echo.
echo [XEYO] Running full pytest (py -3.11) ... log -> logs\pytest-baseline.log
echo        This can take several minutes; the window stays open.
echo.
set "PYTHONIOENCODING=utf-8"
pushd python
py -3.11 -m pytest -q -p no:cacheprovider --tb=line --no-header -rf > "..\logs\pytest-baseline.log" 2>&1
echo.
echo pytest finished. Exit code: %ERRORLEVEL%
popd
echo.
echo ============================================================
echo  DONE. Full html-less summary is in logs\pytest-baseline.log
echo  Showing last lines now ...
echo ============================================================
echo.
powershell -NoProfile -Command "Get-Content -LiteralPath 'logs\pytest-baseline.log' -Encoding utf8 | Select-Object -Last 14"
echo.
echo  Press any key to close this window.
pause >nul
endlocal
