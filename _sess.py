# -*- coding: utf-8 -*-
"""扫 ~/.xeyo/sessions 找循环：相同工具调用重复 / 复读文本。"""
import json, os, time
from collections import Counter
from pathlib import Path

D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
print("sessions dir:", D, "存在:", D.exists())
fs = sorted(D.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
print("会话数:", len(fs))
print()
hdr = f"{'sid':46s} {'assist':>6s} {'tools':>6s} {'distinct':>8s} {'maxrep':>6s} {'textrep':>7s} {'最后写':16s} 最重复调用"
print(hdr)
rows = []
for p in fs:
    try:
        lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except Exception:
        continue
    calls = Counter(); texts = Counter(); asst = 0; tools = 0
    for x in lines:
        if not isinstance(x, dict): continue
        if x.get("role") == "assistant":
            asst += 1
            c = x.get("content")
            if isinstance(c, str) and c.strip(): texts[c.strip()[:200]] += 1
            if isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict): continue
                    if b.get("type") == "text" and str(b.get("text", "")).strip():
                        texts[str(b["text"]).strip()[:200]] += 1
                    if b.get("type") == "tool_use":
                        tools += 1
                        calls[str(b.get("name")) + "|" + json.dumps(b.get("input"), sort_keys=True, ensure_ascii=False)[:400]] += 1
    mc = calls.most_common(1)[0] if calls else ("", 0)
    mt = texts.most_common(1)[0] if texts else ("", 0)
    rows.append((p.stem, asst, tools, len(calls), mc[1], mt[1],
                 time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime)), mc[0][:66]))
rows.sort(key=lambda r: -(r[4] + r[5]))
for r in rows[:22]:
    print(f"{r[0][:46]:46s} {r[1]:6d} {r[2]:6d} {r[3]:8d} {r[4]:6d} {r[5]:7d} {r[6]:16s} | {r[7]}")
print()
print("总会话:", len(rows))
print("maxrep>=5 的会话:", sum(1 for r in rows if r[4] >= 5))
print("textrep>=3 的会话:", sum(1 for r in rows if r[5] >= 3))
print("tools>=60 的会话:", sum(1 for r in rows if r[2] >= 60))
