# -*- coding: utf-8 -*-
"""扫 09-14 19:00 之后被写过的会话 + 全部会话里的循环嫌疑（同签名重复，不要求输出相同）。"""
import json, os, time, re
from collections import Counter, defaultdict
from pathlib import Path

D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
fs = sorted(D.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
CUT = time.mktime(time.strptime("2026-09-14 19:00", "%Y-%m-%d %H:%M"))

def scan(p):
    try:
        lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except Exception:
        return None
    calls = []; asst = 0
    for i, x in enumerate(lines):
        if not isinstance(x, dict): continue
        if x.get("role") == "assistant":
            asst += 1
            c = x.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        calls.append((i, str(b.get("name")),
                                      json.dumps(b.get("input"), sort_keys=True, ensure_ascii=False)))
    sig = [f"{n}|{a[:400]}" for _, n, a in calls]
    c = Counter(sig)
    # 最长连续同签名段
    best = cur = 0; bk = ""
    for k in sig:
        if k == bk: cur += 1
        else: cur = 1; bk = k
        if cur > best: best = cur
    mc = c.most_common(1)[0] if c else ("", 0)
    return {"asst": asst, "tools": len(calls), "distinct": len(c), "maxrep": mc[1],
            "maxrun": best, "top": mc[0][:70], "mt": p.stat().st_mtime, "n": len(lines)}

print("=== 09-14 19:00 之后写过的会话 ===")
rows = []
for p in fs:
    if p.stat().st_mtime < CUT: continue
    r = scan(p)
    if r: rows.append((p.stem, r))
rows.sort(key=lambda t: -t[1]["maxrun"])
print(f"{'sid':46s} {'assist':>6s} {'tools':>6s} {'distinct':>8s} {'maxrep':>6s} {'最长连续':>8s} {'写':16s} 签名")
for sid, r in rows[:25]:
    print(f"{sid[:46]:46s} {r['asst']:6d} {r['tools']:6d} {r['distinct']:8d} {r['maxrep']:6d} {r['maxrun']:8d} "
          f"{time.strftime('%H:%M', time.localtime(r['mt'])):16s} {r['top'][:44]}")
print()
print("19:00 后会话数:", len(rows), "其中 最长连续>=10 的:", sum(1 for _, r in rows if r["maxrun"] >= 10))

print()
print("=== 全量会话：最长连续同签名 >= 10 的全部 ===")
allr = []
for p in fs:
    r = scan(p)
    if r: allr.append((p.stem, r))
allr.sort(key=lambda t: -t[1]["maxrun"])
for sid, r in allr[:12]:
    print(f"{sid[:46]:46s} 最长连续={r['maxrun']:4d} maxrep={r['maxrep']:4d} tools={r['tools']:4d} "
          f"{time.strftime('%m-%d %H:%M', time.localtime(r['mt'])):16s} {r['top'][:40]}")
