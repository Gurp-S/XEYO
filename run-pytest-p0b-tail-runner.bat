@echo off
REM XEYO P0b tail runner (detached; immune to console Ctrl+C).
REM Delegates to run_p0b_tail_batches.py: splits the 98-file list into small
REM independent batches, each pytest DETACHED + unbuffered (-s / PYTHONUNBUFFERED),
REM so any death point leaves visible output and other batches still complete.
pushd "%~dp0python"
py -3.11 "%~dp0run_p0b_tail_batches.py"
set "RC=%ERRORLEVEL%"
popd
echo [XEYO] tail batches finished, rc=%RC%
exit /b %RC%
