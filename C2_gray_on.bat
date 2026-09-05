@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem ============================================================================
rem  XEYO C2 GRAY: turn ON "allow C2 for VERY LONG sessions" (user-level env).
rem
rem  Semantics: XEYO_C2_GATE=1 allows the compact formula to trigger C2 ONLY for
rem  sessions that approach the model window (formula HardTop/soft-top AND Q>=theta*).
rem  Normal sessions still never trigger C2. Runtime default is OFF (DEFAULT_C2_GATE=False).
rem  Applied to newly launched processes (setx writes the user-level env var).
rem ============================================================================
setx XEYO_C2_GATE 1 >nul
echo [C2 GRAY] set user-level XEYO_C2_GATE=1  (takes effect for NEW XEYO/Bash processes).
echo            Only very-long sessions (near window) will allow C2; normal sessions are unaffected.
echo            Pair with daily A3 monitoring (A3_daily_monitor.bat). See docs/A3-monitor-and-c2-gray.md
