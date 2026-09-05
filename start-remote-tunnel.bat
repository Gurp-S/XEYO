@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Expose local XEYO (:8000) via Cloudflare quick tunnel for phone access.
REM Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
REM Keep XEYO.bat (or the Python server) running first.

if not defined XEYO_HTTP_HOST set "XEYO_HTTP_HOST=127.0.0.1"
if not defined XEYO_HTTP_PORT set "XEYO_HTTP_PORT=8000"

if exist "%~dp0.env" (
  for /f "usebackq tokens=* eol=#" %%i in ("%~dp0.env") do (
    for /f "tokens=1,* delims==" %%a in ("%%i") do (
      if not "%%~a"=="" set "%%~a=%%~b"
    )
  )
)

where cloudflared >nul 2>&1
if errorlevel 1 (
  echo.
  echo   ERROR: cloudflared not found on PATH.
  echo   Install from:
  echo   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  echo.
  pause
  exit /b 1
)

echo.
echo   XEYO remote tunnel
echo   ---------------------
echo   Target: http://%XEYO_HTTP_HOST%:%XEYO_HTTP_PORT%
echo   After tunnel starts, open the https URL + /remote/ on your phone.
echo   Set XEYO_REMOTE_TOKEN and XEYO_MODEL_API_KEY in .env first.
echo.

cloudflared tunnel --url "http://%XEYO_HTTP_HOST%:%XEYO_HTTP_PORT%"
set "EXITCODE=%ERRORLEVEL%"
echo.
pause
endlocal & exit /b %EXITCODE%
