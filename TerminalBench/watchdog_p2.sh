#!/usr/bin/env bash
# 余额看门狗 v3：msys PID 存活探测 + Windows taskkill 树杀
set -u
cd "D:/lea/XenYon code/TerminalBench"
ALERT_CNY=6
KEY=$(tr -d '\r\n' < "D:/lea/XenYon code/api_key.txt")
LOG=logs/watchdog.log
WPID=$(cat p2_harbor.pid 2>/dev/null || true)
WINPID=$(grep -oE "^PID=[0-9]+" harbor_winpid.txt 2>/dev/null | head -1 | cut -d= -f2)
echo "watchdog v3 start $(date), msyspid=$WPID winpid=$WINPID" >> "$LOG"
[ -z "$WPID" ] && { echo "no pid, exit" >> "$LOG"; exit 0; }
while true; do
  kill -0 "$WPID" 2>/dev/null || { echo "$(date) harbor exited, watchdog exit" >> "$LOG"; exit 0; }
  BAL=$(curl -s --max-time 15 -H "Authorization: Bearer $KEY" https://api.deepseek.com/user/balance | py -3.11 -c "
import json,sys
try: print(float(json.load(sys.stdin)['balance_infos'][0]['total_balance']))
except Exception: print(-1)
")
  echo "$(date) balance=$BAL" >> "$LOG"
  KILL=$(py -3.11 -c "print(1 if 0 <= $BAL < $ALERT_CNY else 0)")
  if [ "$KILL" = "1" ]; then
    echo "$(date) LOW BALANCE $BAL -> taskkill winpid=$WINPID" >> "$LOG"
    [ -n "$WINPID" ] && taskkill /PID "$WINPID" /T /F
    echo "$(date) killed, exit" >> "$LOG"
    exit 0
  fi
  sleep 600
done
