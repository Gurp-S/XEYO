@echo off
rem ============================================================
rem  Batch 2/3/4 one-click checks: T_now slimming
rem  (B2 nested tail-window / B3 memory index retirement /
rem   B4 approved-plan decay). Double-click to run.
rem ============================================================
setlocal
set ROOT=%~dp0
chcp 65001 >nul

echo ======== [1/2] pytest subset (T_now inject / nested / plan / memory) ========
pushd "%ROOT%python"
py -3.11 -m pytest tests\test_p1_block_placement.py tests\test_pre_llm_inject.py tests\test_main_loop_three_cuts.py tests\test_runtime_c2.py tests\test_multi_agent_p0.py tests\test_multi_agent_hard_gate.py tests\test_multi_agent_p1_toolpath.py tests\test_memory_index_digest.py tests\test_memory_tool.py tests\test_session_presence.py tests\test_cross_session_memory.py tests\test_instruction_maintain.py tests\test_memdir.py -q
set RC=%ERRORLEVEL%
popd

echo.
echo pytest exit code: %RC%
echo (close this window when done)
pause
exit /b %RC%
