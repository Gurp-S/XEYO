# -*- coding: utf-8 -*-
import json, os
from pathlib import Path
D = Path(os.path.expanduser("~")) / ".xeyo" / "sessions"
for sid in ("sess_mu13xpx7_fuv8ld", "sess_mu17emly_x5wpq1", "sess_mu0oo235_9vv9m2", "sess_mu0mkitk_5aehjt"):
    p = D / f"{sid}.jsonl"
    if not p.exists():
        print(f"--- {sid}: 不存在"); continue
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    print("=" * 90)
    print(f"--- {sid}  消息 {len(lines)}")
    # 用户消息
    for x in lines:
        if isinstance(x, dict) and x.get("role") == "user":
            c = x.get("content")
            s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            print("  [USER]", s.replace("\n", " ")[:160])
    print("  工具序列:")
    seq = []
    for x in lines:
        if isinstance(x, dict) and x.get("role") == "assistant" and isinstance(x.get("content"), list):
            for b in x["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    hint = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("action") or json.dumps(inp, ensure_ascii=False)
                    seq.append(f"{b.get('name')}({str(hint)[:70]})")
    for i, s in enumerate(seq):
        print(f"    {i:3d} {s}")
