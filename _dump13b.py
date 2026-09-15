# -*- coding: utf-8 -*-
import json, os
from pathlib import Path
D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
p = D / "sess_mu13xpx7_fuv8ld.jsonl"
lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
print("总消息:", len(lines))
print("=== [34] 之后 ===")
for i, x in enumerate(lines):
    if i < 34: continue
    if not isinstance(x, dict): continue
    role = x.get("role"); c = x.get("content")
    if role == "user":
        s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        print(f"\n### [{i}] USER: {s[:220]}")
    elif role == "ui_thought":
        s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        print(f"    [{i}] THOUGHT({len(s)}): {s[:150]}")
    elif role == "assistant":
        if isinstance(c, str): print(f"    [{i}] ASST: {c[:200]}")
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                if b.get("type") == "text" and str(b.get("text","")).strip():
                    print(f"    [{i}] ASST-TEXT: {str(b['text']).strip()[:200]}")
                elif b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    h = inp.get("command") or inp.get("file_path") or inp.get("pattern") or json.dumps(inp, ensure_ascii=False)
                    print(f"    [{i}] TOOL {b.get('name')}: {str(h)[:140]}")
    elif role == "tool":
        cc = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        print(f"    [{i}] TOOLRES: {cc[:120]}")
print()
print("=== 原始 [17][18] 两条 ===")
print(json.dumps(lines[17], ensure_ascii=False)[:700])
print(json.dumps(lines[18], ensure_ascii=False)[:700])
