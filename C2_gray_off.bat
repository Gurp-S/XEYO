@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem ============================================================================
rem  XEYO C2 GRAY: turn OFF "allow C2 for VERY LONG sessions" (user-level env).
rem  After this, C2 reverts to the runtime default (OFF, DEFAULT_C2_GATE=False).
rem ============================================================================
setx XEYO_C2_GATE 0 >nul
echo [C2 GRAY] set user-level XEYO_C2_GATE=0  (C2 now OFF; long sessions will not compress).
