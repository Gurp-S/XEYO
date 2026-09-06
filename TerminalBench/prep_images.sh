#!/usr/bin/env bash
# P2 前置 v2：SE+Debug 31 题镜像 → crane+Clash 拉取 → 容器内补丁 → commit 同名 tag
# 用法: bash prep_p2_images.sh <names_file> <log_file>
set -u
cd "D:/lea/XenYon code/TerminalBench"
export HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897
NAMES_FILE="${1:-prep_rest_list.json}"
LOG="${2:-logs/prep.log}"
: > "$LOG"

NAMES=$(py -3.11 -c "
import json,sys
print('\n'.join(json.load(open('$NAMES_FILE',encoding='utf-8'))))
" | tr -d '\r')

OK=0; FAIL=0; SKIP=0
FAILED_LIST=""
for n in $NAMES; do
  img="alexgshaw/$n:20251031"
  echo "=== [$n] ===" | tee -a "$LOG"
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    pulled=0
    for attempt in 1 2 3; do
      ./crane.exe pull --platform linux/amd64 "$img" "img_$n.tar" >> "$LOG" 2>&1 && { pulled=1; break; }
      echo "crane attempt $attempt failed" | tee -a "$LOG"; sleep 8
    done
    [ $pulled -eq 1 ] || { echo "PULL-FAILED $n" | tee -a "$LOG"; FAIL=$((FAIL+1)); FAILED_LIST="$FAILED_LIST $n"; continue; }
    docker load < "img_$n.tar" >> "$LOG" 2>&1 || { echo "LOAD-FAILED $n" | tee -a "$LOG"; FAIL=$((FAIL+1)); rm -f "img_$n.tar"; continue; }
    rm -f "img_$n.tar"
  else
    echo "image cached" | tee -a "$LOG"
    SKIP=$((SKIP+1))
  fi
  c="prep_$n"
  docker rm -f "$c" >/dev/null 2>&1
  if docker run -d --name "$c" "$img" sleep 3600 >/dev/null 2>&1; then
    if docker exec -i "$c" sh -s < patch_inside.sh >> "$LOG" 2>&1; then
      docker commit "$c" "$img" >> "$LOG" 2>&1
      echo "PATCHED $n" | tee -a "$LOG"; OK=$((OK+1))
    else
      echo "PATCH-FAILED $n" | tee -a "$LOG"; FAIL=$((FAIL+1)); FAILED_LIST="$FAILED_LIST $n"
    fi
    docker rm -f "$c" >/dev/null 2>&1
  else
    echo "RUN-FAILED $n" | tee -a "$LOG"; FAIL=$((FAIL+1)); FAILED_LIST="$FAILED_LIST $n"
  fi
done
echo "PREP-DONE ok=$OK fail=$FAIL skipcached=$SKIP" | tee -a "$LOG"
[ -n "$FAILED_LIST" ] && echo "FAILED_TASKS:$FAILED_LIST" | tee -a "$LOG"
exit 0
