#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析 editflick 矩阵日志:对每场景 JSON trace 标记 >1.5px 跳变帧(Esc 前后窗口)。"""
import io, re, sys, json

LOG = r"C:/Users/48522/AppData/Local/Temp/editflick-matrix.log"
raw = io.open(LOG, encoding="utf-8", errors="replace").read()

# 按场景切块:=== TRACE <label> ===\n[JSON]\n=== MAX-JUMP <label>: <v>px ===
blocks = re.findall(
    r"=== TRACE ([^\n=]+) ===\n(\[.*?\])\n=== MAX-JUMP \1: ([0-9.]+)px ===",
    raw,
    flags=re.S,
)
if not blocks:
    # 单场景日志
    blocks = re.findall(
        r"=== TRACE ([^\n=]+) ===\n(\[.*?\])\n=== MAX-JUMP \1: ([0-9.]+)px ===",
        raw,
        flags=re.S,
    )

for label, js, mx in blocks:
    try:
        rec = json.loads(js)
    except Exception as e:
        print(f"[{label}] JSON parse error: {e}")
        continue
    print(f"\n===== {label} (报告 MAX-JUMP {mx}px) =====")
    prev = None
    for r in rec:
        row = (r.get("aTop"), r.get("ebTop"), r.get("ebH"), r.get("cTop"))
        if prev is not None:
            d_a = abs(row[0] - prev[0]) if (row[0] is not None and prev[0] is not None) else 0
            d_e = abs(row[1] - prev[1]) if (row[1] is not None and prev[1] is not None) else 0
            d_h = abs(row[2] - prev[2]) if (row[2] is not None and prev[2] is not None) else 0
            if max(d_a, d_e, d_h) > 1.5:
                flag = []
                if d_a > 1.5:
                    flag.append(f"aTop {prev[0]}->{row[0]}")
                if d_e > 1.5:
                    flag.append(f"ebTop {prev[1]}->{row[1]}")
                if d_h > 1.5:
                    flag.append(f"ebH {prev[2]}->{row[2]}")
                print(
                    f"  dt={r.get('dt')} 跳帧: {'; '.join(flag)} | "
                    f"closing={r.get('closing')} ebOp={r.get('ebOp')} gtr={r.get('gtr')} "
                    f"cVis={r.get('cVis')} st={r.get('st')}"
                )
        prev = row
print("\ndone")
