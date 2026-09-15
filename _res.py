# -*- coding: utf-8 -*-
import json, os, hashlib
from pathlib import Path
D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
p = D / "sess_mu17emly_x5wpq1.jsonl"
lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]

def norm_result(x):
    c = x.get("content")
    if isinstance(c, str): return c
    if isinstance(c, list):
        out = []
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                cc = b.get("content")
                out.append(cc if isinstance(cc, str) else json.dumps(cc, ensure_ascii=False))
        return "\n".join(out)
    return ""

# 抓工具调用与其结果
calls = []
for i, x in enumerate(lines):
    if isinstance(x, dict) and x.get("role") == "assistant" and isinstance(x.get("content"), list):
        for b in x["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                calls.append((i, b.get("id"), str(b.get("name")), b.get("input") or {}))
res_of = {}
for x in lines:
    if isinstance(x, dict) and x.get("role") == "tool":
        tid = x.get("tool_call_id")
        if tid: res_of[tid] = norm_result(x)

print(f"{'#':>3s} {'tool':10s} {'target':52s} {'结果 sha1':>12s} {'长度':>6s}  头 90 字")
for k, (i, tid, name, inp) in enumerate(calls):
    tgt = inp.get("file_path") or inp.get("command") or inp.get("pattern") or json.dumps(inp, ensure_ascii=False)
    r = res_of.get(tid, "")
    h = hashlib.sha1(r.encode()).hexdigest()[:12] if r else "-"
    print(f"{k:3d} {name:10s} {str(tgt)[:52]:52s} {h:>12s} {len(r):6d}  {r[:90]!r}")
