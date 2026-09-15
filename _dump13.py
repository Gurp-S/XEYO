# -*- coding: utf-8 -*-
import json, os
from pathlib import Path
D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
p = D / "sess_mu13xpx7_fuv8ld.jsonl"
lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
for i, x in enumerate(lines):
    if not isinstance(x, dict): continue
    role = x.get("role")
    c = x.get("content")
    if role == "user":
        s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        print(f"\n### [{i}] USER: {s[:200]}")
    elif role == "ui_thought":
        s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        print(f"    [{i}] THOUGHT({len(s)}): {s[:170]}")
    elif role == "assistant":
        if isinstance(c, str):
            print(f"    [{i}] ASST: {c[:220]}")
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                if b.get("type") == "text":
                    t = str(b.get("text","")).strip()
                    if t: print(f"    [{i}] ASST-TEXT: {t[:220]}")
                elif b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    h = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("action") or json.dumps(inp, ensure_ascii=False)
                    print(f"    [{i}] TOOL {b.get('name')}: {str(h)[:150]}")
                elif b.get("type") == "thinking":
                    t = str(b.get("thinking","")).strip()
                    if t: print(f"    [{i}] THINKING({len(t)}): {t[:170]}")
    elif role == "tool":
        cc = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        print(f"    [{i}] TOOLRES: {cc[:130]}")
