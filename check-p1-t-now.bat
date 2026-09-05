@echo off
rem ============================================================
rem  P1 one-click checks: T_now structural fix
rem  (A1 placement / D1 vague-turn gating / F1 real budget cap /
rem   F3 block classes). Double-click to run. Read-only tests.
rem ============================================================
setlocal
set ROOT=%~dp0
chcp 65001 >nul

echo ======== [1/2] pytest subset (T_now inject / placement / memory) ========
pushd "%ROOT%python"
py -3.11 -m pytest tests\test_p1_block_placement.py tests\test_pre_llm_inject.py tests\test_main_loop_three_cuts.py tests\test_runtime_c2.py tests\test_multi_agent_p0.py tests\test_multi_agent_hard_gate.py tests\test_memory_index_digest.py tests\test_memdir.py tests\test_memory_tool.py -q
set RC=%ERRORLEVEL%
popd

echo.
echo pytest exit code: %RC%
echo (close this window when done)
pause
exit /b %RC%
