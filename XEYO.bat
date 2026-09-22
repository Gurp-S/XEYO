@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM ============================================================
REM  XEYO launcher (dev / hot-reload)
REM  - Browser dev: Vite hot-reloads gui\src changes
REM  - Backend: FastAPI, waits for /health before launching frontend
REM  - Both console windows share backend/frontend logs
REM  How to use: double-click this file, or run it in cmd: XEYO.bat
REM ============================================================

REM ---------- env setup ----------
if not exist "%~dp0.env" if exist "%~dp0.env.example" copy /y "%~dp0.env.example" "%~dp0.env" >nul

if exist "%~dp0.env" (
  for /f "usebackq tokens=* eol=#" %%i in ("%~dp0.env") do (
    for /f "tokens=1,* delims==" %%a in ("%%i") do if not "%%~a"=="" set "%%~a=%%~b"
  )
)

if not defined XEYO_PYTHON_ROOT set "XEYO_PYTHON_ROOT=%~dp0python"
if not defined PYTHONUNBUFFERED set "PYTHONUNBUFFERED=1"
if not defined PYTHONIOENCODING set "PYTHONIOENCODING=utf-8"
if not defined XEYO_HTTP_HOST set "XEYO_HTTP_HOST=127.0.0.1"
if not defined XEYO_HTTP_PORT set "XEYO_HTTP_PORT=8000"
if not defined XEYO_FRONTEND_PORT set "XEYO_FRONTEND_PORT=5173"
if not defined XEYO_CORS_ORIGIN set "XEYO_CORS_ORIGIN=http://localhost:%XEYO_FRONTEND_PORT%"
REM Per-run log path: a unique name so a stale holder from a previous run can never
REM lock the same file and block a new launch with a file-sharing violation.
if not defined XEYO_PY_LOG_TAG set "XEYO_PY_LOG_TAG=%RANDOM%"
set "XEYO_PY_LOG=%TEMP%\xeyo-python_%XEYO_PY_LOG_TAG%.log"
REM Local models are not started by this script: the backend owns those processes, and
REM enabling one is a setting under Settings - Models and Accounts - Local model,
REM persisted in ~/.xeyo/settings.json. This script only does two things: scavenge
REM leftovers from the previous run before start, and scavenge this run's leftovers
REM after exit as a hard-kill fallback.

echo.
echo   XEYO - launcher (dev / hot-reload)
echo   ----------------------------------------
echo.

REM ---------- frontend prereqs ----------
where node >nul 2>&1
if errorlevel 1 goto ERR_NODE

where py >nul 2>&1
if errorlevel 1 goto ERR_PY

py -3.11 -c "import sys; assert sys.version_info[:2]==(3,11)" >nul 2>&1
if errorlevel 1 goto ERR_PY311

echo   Checking Python deps...
py -3.11 -c "import fastapi,uvicorn,multipart,PIL" >nul 2>&1
if errorlevel 1 goto INSTALL_PY
echo   Python deps OK.

goto AFTER_PY

:INSTALL_PY
echo   Installing Python deps...
py -3.11 -m pip install -q -r "%~dp0python\requirements.txt"
if errorlevel 1 (
  echo   ERROR: pip install failed. Fix Python deps and retry.
  echo   Tip: run  py -3.11 -m pip install -r "%~dp0python\requirements.txt"  manually.
  pause
  exit /b 1
)

:AFTER_PY
if exist "%~dp0gui\node_modules\" goto AFTER_NPM
echo   First run: npm install...
pushd "%~dp0gui"
call npm install
if errorlevel 1 (
  popd
  goto ERR_NPM
)
popd

:AFTER_NPM
REM Free stale listeners on both the backend and frontend port first (port-occupied fix).
call :FREE_PORT

REM Scavenge local-model processes left over from a crash (they keep holding VRAM and the port)
call :SCAVENGE_LOCAL_MODEL

REM ---------- start backend (background) + wait for /health ----------
echo   Starting FastAPI backend on http://%XEYO_HTTP_HOST%:%XEYO_HTTP_PORT% ...
pushd "%XEYO_PYTHON_ROOT%"
start "XEYO-Python" /b py -3.11 -u -m server > "%XEYO_PY_LOG%" 2>&1
popd

REM Let wait_health resolve the real backend port (it auto-moves if the configured one was occupied).
py -3.11 "%~dp0python\scripts\wait_health.py" "http://%XEYO_HTTP_HOST%:{PORT}/health" 25 "%~dp0.xeyo\backend_port"
if errorlevel 1 goto ERR_BRIDGE

REM Now the port file is guaranteed written; read it for the frontend (T30: JSON {port,pid,...}).
set "ACTUAL_PORT=%XEYO_HTTP_PORT%"
if exist "%~dp0.xeyo\backend_port" (
  for /f "usebackq delims=" %%a in (`py -3.11 "%~dp0python\scripts\read_port.py" "%~dp0.xeyo\backend_port"`) do set "ACTUAL_PORT=%%a"
)
if not "%ACTUAL_PORT%"=="%XEYO_HTTP_PORT%" echo   Backend auto-using port %ACTUAL_PORT% (configured %XEYO_HTTP_PORT% was occupied).
echo   Backend ready.

REM ---------- start frontend (Tauri dev / Vite hot-reload) ----------
REM Rust/cargo required for the Tauri desktop window; browser dev uses: cd gui && npm run dev.
cargo --version >nul 2>&1
if errorlevel 1 (
  echo   ERROR: Rust/cargo not found. The Tauri desktop window needs Rust ^(install from https://rustup.rs^).
  echo   For browser-only dev, run:  cd gui ^&^& npm run dev
  pause
  exit /b 1
)

set "VITE_XEYO_HTTP_PORT=%ACTUAL_PORT%"
pushd "%~dp0gui"
call npm run tauri:dev
set "EXITCODE=%ERRORLEVEL%"
popd
call :FREE_PORT
REM Closing XEYO closes the local model too. The backend's shutdown hook handles the
REM normal path; this call covers hard-kill and crash.
call :STOP_LOCAL_MODEL
if not "%EXITCODE%"=="0" goto ERR_TAURI
goto DONE

REM ---------- exit ----------
:DONE
echo   Exit code: %EXITCODE%
endlocal & exit /b %EXITCODE%

:FREE_PORT
REM T30: backend cleanup by pid tree from the port file
if exist "%~dp0.xeyo\backend_port" (
  for /f "usebackq delims=" %%a in (`py -3.11 "%~dp0python\scripts\read_port.py" "%~dp0.xeyo\backend_port" --pid`) do taskkill /PID %%a /T /F >nul 2>&1
)
if defined XEYO_FRONTEND_PORT (
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%XEYO_FRONTEND_PORT% " ^| findstr LISTENING') do taskkill /PID %%p /T /F >nul 2>&1
)
exit /b 0

REM ===== Local model (llama.cpp) lifecycle fallback; the backend owns the processes, this only cleans up =====
REM Kills the whole process tree via the pid in ~/.xeyo/local-models/run/run.json.
REM The backend does this itself on a normal exit; these two hooks cover "Python was hard-killed".
:SCAVENGE_LOCAL_MODEL
py -3.11 "%~dp0python\scripts\local_model_ctl.py" --stop >nul 2>&1
exit /b 0

:STOP_LOCAL_MODEL
py -3.11 "%~dp0python\scripts\local_model_ctl.py" --stop >nul 2>&1
exit /b 0

:ERR_NODE
echo.
echo   ERROR: Node.js not found. Please install Node.js 20+.
pause
exit /b 1

:ERR_PY
echo.
echo   ERROR: Python launcher "py" not found.
pause
exit /b 1

:ERR_PY311
echo.
echo   ERROR: Python 3.11 required (found different version).
echo   Install Python 3.11 and make sure "py -3.11" works.
pause
exit /b 1

:ERR_NPM
echo.
echo   ERROR: npm install failed in gui\.
pause
exit /b 1

:ERR_BRIDGE
echo.
echo   ERROR: FastAPI did not become healthy on port %XEYO_HTTP_PORT%.
echo   Tip: check %XEYO_PY_LOG%
pause
exit /b 1

:ERR_TAURI
echo.
echo   ERROR: Tauri dev failed (exit %EXITCODE%).
echo   Try: cd gui ^&^& npm run tauri:dev
pause
exit /b 1