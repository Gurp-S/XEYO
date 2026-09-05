@echo off
rem ============================================================
rem  XEYO GUI perf benchmark one-click runner (P0 baseline)
rem  Double-click me. This script:
rem    1. starts gui dev server on 127.0.0.1:5177 (separate window,
rem       IPv4 pinned so probing and the browser URL always match)
rem    2. waits until it is ready (max 90s)
rem    3. opens the auto-bench page; the page then runs
rem       rounds=5000 -> 2000 -> 500 automatically and downloads
rem       one xy-bench-r*.json per size into your Downloads folder
rem
rem  Notes:
rem    - First download triggers a browser "allow multiple
rem      downloads?" prompt -> click allow.
rem    - Keep the tab in the foreground while it runs (2-4 min).
rem    - The browser console prints a PASS/FAIL budget table.
rem ============================================================
setlocal
cd /d "%~dp0gui"

rem -- already a dev server on 127.0.0.1:5177? reuse it.
powershell -NoProfile -Command "try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', 5177); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto READY

echo [bench] starting gui dev server on 127.0.0.1:5177 (new window)...
start "XEYO bench dev" cmd /k pnpm dev --port 5177 --strictPort --host 127.0.0.1

echo [bench] waiting for dev server (max 90 seconds)...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(90); while((Get-Date) -lt $deadline){ try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',5177); $c.Close(); exit 0 } catch { Start-Sleep -Milliseconds 500 } } exit 1" >nul 2>&1
if errorlevel 1 goto DEVFAIL

:READY
echo [bench] opening auto-bench page (3 sizes, about 2-4 minutes)...
start "" "http://127.0.0.1:5177/bench/chat?rounds=5000&bench=1&auto=1"
echo.
echo [bench] DONE-WAIT: when the page finishes, 3 files named
echo         xy-bench-r*.json appear in your Downloads folder.
echo         Send them back to the agent. Console also prints a
echo         PASS/FAIL budget table.
echo.
pause
exit /b 0

:DEVFAIL
echo.
echo [bench] ERROR: dev server did not become reachable on 127.0.0.1:5177
echo         (waited 90 seconds). Check the "XEYO bench dev" window:
echo         if vite printed a DIFFERENT port there, or pnpm/vite
echo         reported an error, send me a screenshot of that window.
echo.
pause
exit /b 1
