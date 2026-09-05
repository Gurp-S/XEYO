@echo off
REM XEYO P0b FULL regression — console-less launcher (NO flashing window).
REM
REM Launches run_p0b_tail_batches.py --all under pythonw (GUI subsystem, no
REM console), so nothing pops/flashes. --all auto-discovers ALL tests/ test files
REM and runs them in small independent batches (immune to console/harness kills).
REM All output goes to log files:
REM   Progress/batch results:  logs\pytest-p0b-tail.summary.txt
REM   Per-batch pytest output:  logs\p0b-batchNN.log  (NN = 01..N)
REM   Per-batch JUnit results:  logs\p0b-batchNN.xml
REM   Done sentinel:            logs\pytest-p0b-tail.done  ("done exit=<0|1>")
REM
REM To watch progress from an already-open terminal (no new window):
REM   powershell "while(!(Test-Path 'logs\pytest-p0b-tail.done')){Get-Content 'logs\pytest-p0b-tail.summary.txt' -Tail 40; sleep 5}"
REM
REM To run only the 98-file tail list instead of the full suite:
REM   py -3.11 run_p0b_tail_batches.py --tail
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
for %%f in (logs\pytest-p0b-tail.done logs\pytest-p0b-tail.summary.txt) do if exist "%%f" del "%%f"
for %%f in (logs\p0b-batch*.log logs\p0b-batch*.xml) do if exist "%%f" del "%%f"
start "" pythonw "%~dp0run_p0b_tail_batches.py" --all
echo [XEYO] FULL P0b regression started (no console window). It runs fully detached, all tests/ in batches.
echo   Progress: logs\pytest-p0b-tail.summary.txt
echo   Batches:  logs\p0b-batchNN.log / logs\p0b-batchNN.xml
echo   Done:     logs\pytest-p0b-tail.done
endlocal
exit /b 0
