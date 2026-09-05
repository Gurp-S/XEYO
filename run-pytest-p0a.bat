@echo off
REM XEYO P0a regression: full pytest, deselect known env-timeout t9 tests.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
set "PYTHONIOENCODING=utf-8"
echo [XEYO] Running full pytest (py -3.11). Log: logs\pytest-p0a-manual.log
pushd python
py -3.11 -m pytest -q -p no:cacheprovider --tb=line --no-header -rf --deselect tests/test_goal_state_t9.py --deselect tests/test_goal_turn_hook_t9.py > "..\logs\pytest-p0a-manual.log" 2>&1
set RC=%ERRORLEVEL%
popd
echo.
echo pytest exit code: %RC%
echo ============ last 25 lines ============
powershell -NoProfile -Command "Get-Content -LiteralPath 'logs\pytest-p0a-manual.log' -Tail 25"
echo.
echo Full log: logs\pytest-p0a-manual.log
pause
endlocal
