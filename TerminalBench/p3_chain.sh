#!/usr/bin/env bash
# P3 自动链：等批1 → 批2(XEYO smoke) → 余额闸门 → 批3(terminus臂 → xeyo臂)
set -u
cd "D:/lea/XenYon code/TerminalBench"
LOG=logs/p3_chain.log
: > "$LOG"
export PYTHONPATH="D:/lea/XenYon code/TerminalBench"
export DEEPSEEK_API_KEY=$(tr -d '\r\n' < "D:/lea/XenYon code/api_key.txt")
export TMP="D:/lea/XenYon code/TerminalBench/.tmp" TEMP="D:/lea/XenYon code/TerminalBench/.tmp"
H=.venv-harbor313/Scripts/harbor

bal() { curl -s --max-time 15 -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/user/balance | py -3.11 -c "
import json,sys
try: print(float(json.load(sys.stdin)['balance_infos'][0]['total_balance']))
except Exception: print(-1)
"; }

echo "$(date) chain start" >> "$LOG"

# 1) 等批1：jobs_p3_infra 出现 7 个 trial result（最多 40 分钟）
for i in $(seq 1 40); do
  N=$(find jobs_p3_infra -name "result.json" -path "*__*" 2>/dev/null | wc -l)
  [ "$N" -ge 7 ] && { echo "$(date) batch1 done ($N)" >> "$LOG"; break; }
  sleep 60
done

# 2) 批2：XEYO smoke（5 calib 题，真实模型）
echo "$(date) batch2 start" >> "$LOG"
"$H" run -c p3_batch2.yaml > logs/p3_batch2.log 2>&1
echo "$(date) batch2 exit=$?" >> "$LOG"

# 3) 余额闸门：< 18 元 → 停链等充值（chain 退出，充值后手动重跑批3两个 yaml）
B=$(bal)
echo "$(date) balance before batch3 = $B" >> "$LOG"
if python_ok=$(py -3.11 -c "print(1 if 0 <= $B < 18 else 0)"); then
  if [ "$python_ok" = "1" ]; then
    echo "$(date) BALANCE LOW ($B) — batch3 NOT started. Recharge then run:" >> "$LOG"
    echo "  $H run -c p3_batch3_term.yaml ; $H run -c p3_batch3_xeyo.yaml" >> "$LOG"
    exit 0
  fi
fi

# 4) 批3 双臂
echo "$(date) batch3-terminus start" >> "$LOG"
"$H" run -c p3_batch3_term.yaml > logs/p3_batch3_term.log 2>&1
echo "$(date) batch3-terminus exit=$?" >> "$LOG"
echo "$(date) batch3-xeyo start" >> "$LOG"
"$H" run -c p3_batch3_xeyo.yaml > logs/p3_batch3_xeyo.log 2>&1
echo "$(date) batch3-xeyo exit=$?" >> "$LOG"
echo "$(date) CHAIN DONE" >> "$LOG"
