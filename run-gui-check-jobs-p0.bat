@echo off
REM XEYO 42 P0 GUI check: typecheck + vitest (jobs badge batch).
REM Double-click to run. No goto/labels (CRLF-safe); always pauses at end.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs

where npm >nul 2>nul
if errorlevel 1 echo [WARN] npm not found on PATH - node/npm may be missing in this shell

echo [XEYO] [1/2] TypeScript typecheck (gui) ...
pushd gui
call npm run typecheck > "..\logs\gui-typecheck-jobs-p0.log" 2>&1
set RC1=%ERRORLEVEL%
popd
powershell -NoProfile -Command "Get-Content -LiteralPath 'logs\gui-typecheck-jobs-p0.log' -Tail 25"
echo typecheck exit code: %RC1%
echo.

echo [XEYO] [2/2] vitest run (gui, full unit suite) ...
pushd gui
call npm test > "..\logs\vitest-jobs-p0.log" 2>&1
set RC2=%ERRORLEVEL%
popd
powershell -NoProfile -Command "Get-Content -LiteralPath 'logs\vitest-jobs-p0.log' -Tail 45"
echo vitest exit code: %RC2%
echo.

if "%RC1%"=="0" if "%RC2%"=="0" echo ============ ALL GREEN: typecheck + vitest ============
if not "%RC1%"=="0" echo ============ FAILED at typecheck (see log above) ============
if not "%RC2%"=="0" echo ============ FAILED at vitest (see log above) ============
pause
endlocal
