@echo off
REM C2 灰度：超长会话允许公式 C2（证据门未齐前勿当生产默认）
REM 已注释：保持默认（project + 阈值自动 C2），避免 dev 入口误开"每轮 decide"。
REM 需显式灰度时取消下一行注释：
rem set XEYO_C2_GATE=1
cd /d "D:\lea\XenYon code\gui"
npm run tauri:dev > "D:\lea\XenYon code\tauri-dev.out.log" 2> "D:\lea\XenYon code\tauri-dev.err.log"
