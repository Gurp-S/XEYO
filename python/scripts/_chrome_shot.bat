@echo off
set URL=file:///D:/lea/XenYon%%20code/docs/A3-monitor.html
"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless --disable-gpu --screenshot="D:\lea\XenYon code\docs\A3-light.png" --window-size=1440,900 "%URL%"
echo light done