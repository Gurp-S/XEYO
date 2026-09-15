# -*- coding: utf-8 -*-
"""扫工作区级 GUI 会话库 D:\lea\XenYon code\.xeyo_sessions 找循环。"""
import json, re, time
from collections import Counter
from pathlib import Path

D = Path(r"D:\lea\XenYon code\.xeyo_sessions")
fs = sorted(D.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
print("文件数:", len(fs))

def norm(s): return re.sub(r"\s+", " ", s or "").strip()[:200]

rows = []
for p in fs:
    try:
        lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except Exception:
        continue
    calls = []
    for x in lines:
        if not isinstance(x, dict): continue
        if x.get("role") == "assistant" and isinstance(x.get("content"), list):
            for b in x["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    calls.append((str(b.get("name")), json.dumps(b.get("input"), sort_keys=True, ensure_ascii=False)))
    sigs = [f"{n}|{norm(a)}" for n, a in calls]
    bapp = capp = 0; ak = ""
    for s in sigs:
        if s == ak: capp += 1
        else: capp = 1; ak = s
        bapp = max(bapp, capp)
    rows.append((p.stem, {"asst": sum(1 for x in lines if isinstance(x, dict) and x.get("role") == "assistant"),
                          "tools": len(calls), "distinct": len(set(sigs)),
                          "maxrep": Counter(sigs).most_common(1)[0][1] if sigs else 0,
                          "run": bapp, "mt": p.stat().st_mtime,
                          "top": Counter(sigs).most_common(1)[0][0][:56] if sigs else "",
                          "n": len(lines)}))
rows.sort(key=lambda t: -t[1]["run"])
print()
print(f"{'sid':40s} {'写':16s} {'msg':>5s} {'assist':>6s} {'tools':>6s} {'近似连':>6s} {'maxrep':>6s}  签名")
for s, r in rows[:25]:
    print(f"{s[:40]:40s} {time.strftime('%m-%d %H:%M', time.localtime(r['mt'])):16s} {r['n']:5d} {r['asst']:6d} "
          f"{r['tools']:6d} {r['run']:6d} {r['maxrep']:6d}  {r['top'][:34]}")
print()
print("循环嫌疑（近似连>=8）:", [(s[:26], r['run']) for s, r in rows if r['run'] >= 8])
