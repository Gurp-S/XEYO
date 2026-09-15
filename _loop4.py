# -*- coding: utf-8 -*-
"""宽口径循环扫描：①同工具名连续 ②近似命令(归一化后同) ③单次 submit 工具数爆炸。"""
import json, os, re, time
from collections import Counter
from pathlib import Path

D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
fs = sorted(D.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
TODAY = time.mktime(time.strptime("2026-09-14 00:00", "%Y-%m-%d %H:%M"))

def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "")
    return s.strip()[:200]

def scan(p):
    try:
        lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except Exception:
        return None
    calls = []
    for i, x in enumerate(lines):
        if not isinstance(x, dict): continue
        if x.get("role") == "assistant" and isinstance(x.get("content"), list):
            for b in x["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    calls.append((i, str(b.get("name")), json.dumps(b.get("input"), sort_keys=True, ensure_ascii=False)))
    names = [n for _, n, _ in calls]
    sigs = [f"{n}|{norm(a)}" for _, n, a in calls]
    # 同工具名连续
    bname = cname = 0; bk = ""
    for n in names:
        if n == bk: cname += 1
        else: cname = 1; bk = n
        bname = max(bname, cname)
    # 近似签名连续
    bapprox = capprox = 0; ak = ""
    for s in sigs:
        if s == ak: capprox += 1
        else: capprox = 1; ak = s
        bapprox = max(bapprox, capprox)
    return {"asst": sum(1 for x in lines if isinstance(x, dict) and x.get("role") == "assistant"),
            "tools": len(calls), "distinct": len(set(sigs)),
            "maxrep": Counter(sigs).most_common(1)[0][1] if sigs else 0,
            "run_name": bname, "run_appr": bapprox,
            "mt": p.stat().st_mtime,
            "top": Counter(sigs).most_common(1)[0][0][:60] if sigs else ""}

rows = [(p.stem, scan(p)) for p in fs]
rows = [(s, r) for s, r in rows if r]
print("=== 今天(09-14) 写过的会话，按『同工具名最长连续』排序 ===")
tod = [(s, r) for s, r in rows if r["mt"] >= TODAY]
tod.sort(key=lambda t: -t[1]["run_name"])
print(f"{'sid':46s} {'写':6s} {'assist':>6s} {'tools':>6s} {'distinct':>8s} {'名连续':>6s} {'近似连':>6s} {'maxrep':>6s}  签名")
for s, r in tod[:28]:
    print(f"{s[:46]:46s} {time.strftime('%H:%M', time.localtime(r['mt'])):6s} {r['asst']:6d} {r['tools']:6d} "
          f"{r['distinct']:8d} {r['run_name']:6d} {r['run_appr']:6d} {r['maxrep']:6d}  {r['top'][:36]}")
print()
print("今天会话数:", len(tod))
print("同工具名连续>=8 的:", [(s[:30], r["run_name"]) for s, r in tod if r["run_name"] >= 8])
print()
print("=== 全量：同工具名连续 >=8 ===")
for s, r in sorted(rows, key=lambda t: -t[1]["run_name"])[:10]:
    if r["run_name"] < 8: break
    print(f"{s[:44]:44s} 名连续={r['run_name']:4d} 近似连={r['run_appr']:4d} tools={r['tools']:4d} "
          f"{time.strftime('%m-%d %H:%M', time.localtime(r['mt']))}  {r['top'][:44]}")
