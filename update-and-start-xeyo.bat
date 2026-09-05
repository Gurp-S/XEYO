@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM ============================================================
REM  XEYO launcher (all entry points - Desktop / Start Menu):
REM  every launch applies the latest built release exe, shows
REM  its build time, then starts the app. No manual update step.
REM  If XEYO is already running, close its window to continue.
REM ============================================================

echo Waiting for xeyo.exe to exit (close the XEYO window now)...
:waitloop
tasklist /FI "IMAGENAME eq xeyo.exe" 2>nul | find /I "xeyo.exe" >nul
if %ERRORLEVEL%==0 (
  timeout /t 2 /nobreak >nul
  goto waitloop
)

for %%F in ("gui\src-tauri\target\release\xeyo.exe") do set "BUILD_TIME=%%~tF"
echo Latest build: %BUILD_TIME%

copy /y "gui\src-tauri\target\release\xeyo.exe" "gui\src-tauri\target\debug\xeyo.exe" >nul
if errorlevel 1 (
  echo [ERROR] Copy failed. Make sure the XEYO window is closed, then retry.
  pause
  exit /b 1
)

echo Applied latest build. Starting XEYO...
start "" "gui\src-tauri\target\debug\xeyo.exe"
exit /b 0
