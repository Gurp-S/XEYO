@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM ============================================================
REM  XEYO TUI (TypeScript / Ink) — double-click entry
REM  Falls back to Python CLI if Node deps are missing.
REM ============================================================

if not defined XEYO_PYTHON_ROOT set "XEYO_PYTHON_ROOT=%~dp0python"
if not defined PYTHONUNBUFFERED set "PYTHONUNBUFFERED=1"
if not defined PYTHONIOENCODING set "PYTHONIOENCODING=utf-8"
if not defined XEYO_CWD set "XEYO_CWD=%~dp0"
if "%XEYO_CWD:~-1%"=="\" set "XEYO_CWD=%XEYO_CWD:~0,-1%"
if not defined XEYO_HTTP_HOST set "XEYO_HTTP_HOST=127.0.0.1"

REM ---------- ensure engine is up (T32: reuse running, else auto-start cli serve) ----------
set "ENGINE_PORT=%XEYO_HTTP_PORT%"
py -3.11 "%~dp0python\scripts\wait_health.py" "http://%XEYO_HTTP_HOST%:{PORT}/health" 3 "%~dp0.xeyo\backend_port" >nul 2>&1
if errorlevel 1 (
  echo   Engine not running — starting (py -3.11 -m cli serve)...
  pushd "%XEYO_PYTHON_ROOT%"
  start "XEYO-Python" /b py -3.11 -u -m cli serve > "%TEMP%\xeyo-python.log" 2>&1
  popd
  py -3.11 "%~dp0python\scripts\wait_health.py" "http://%XEYO_HTTP_HOST%:{PORT}/health" 25 "%~dp0.xeyo\backend_port"
  if errorlevel 1 (
    echo   ERROR: Engine failed to start. See %TEMP%\xeyo-python.log
    pause
    exit /b 1
  )
)
if exist "%~dp0.xeyo\backend_port" for /f "usebackq delims=" %%a in (`py -3.11 "%~dp0python\scripts\read_port.py" "%~dp0.xeyo\backend_port"`) do set "ENGINE_PORT=%%a"
if not defined XEYO_SERVER_URL set "XEYO_SERVER_URL=http://%XEYO_HTTP_HOST%:%ENGINE_PORT%"
echo   Engine ready at %XEYO_SERVER_URL%

echo.
echo   XEYO TUI  —  I am XEYO  (TypeScript)
echo   ----------------------------------------
echo.

where node >nul 2>&1
if errorlevel 1 goto FALLBACK_PY

if not exist "%~dp0tui\node_modules\" (
  echo   First run: npm install in tui...
  pushd "%~dp0tui"
  call npm install
  if errorlevel 1 (
    popd
    echo   npm install failed — falling back to Python CLI.
    goto FALLBACK_PY
  )
  popd
)

REM Live chat by default. Pass --demo for a one-shot UI showcase.
pushd "%~dp0tui"
call npx --yes tsx src/index.tsx --cwd "%XEYO_CWD%" %*
set "EXITCODE=%ERRORLEVEL%"
popd
goto DONE

:FALLBACK_PY
echo   Using Python CLI fallback...
where py >nul 2>&1
if errorlevel 1 (
  echo   ERROR: Need Node.js 20+ or Python 3.11.
  pause
  exit /b 1
)
pushd "%XEYO_PYTHON_ROOT%"
py -3.11 -m cli %*
set "EXITCODE=%ERRORLEVEL%"
popd

:DONE
echo.
if not "%EXITCODE%"=="0" echo   Exit code: %EXITCODE%
pause
endlocal & exit /b %EXITCODE%
