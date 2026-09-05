@echo off
rem ============================================================
rem  P0 one-click checks: Memory index block (digest / fence /
rem  unconditional wording). Double-click to run.
rem  No server / engine needed. Read-only + pytest subset.
rem ============================================================
setlocal
set ROOT=%~dp0
chcp 65001 >nul

echo ======== [1/2] pytest subset (memory index / T_now inject) ========
pushd "%ROOT%python"
py -3.11 -m pytest tests\test_memory_index_digest.py tests\test_pre_llm_inject.py tests\test_main_loop_three_cuts.py tests\test_runtime_c2.py tests\test_multi_agent_p0.py tests\test_multi_agent_hard_gate.py tests\test_memdir.py tests\test_memory_tool.py -q
set RC=%ERRORLEVEL%
popd

echo.
echo ======== [2/2] live Memory index T_now block preview ========
py -3.11 "%ROOT%python\scripts\preview_memory_index_block.py" "%ROOT%."

echo.
echo pytest exit code: %RC%
echo (close this window when done)
pause
exit /b %RC%
