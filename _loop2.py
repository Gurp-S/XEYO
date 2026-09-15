# -*- coding: utf-8 -*-
import json, os, hashlib
from pathlib import Path
p = Path(os.path.expanduser("~")) / ".xeyo" / "sessions" / "sess_mu0mkitk_5aehjt.jsonl"
lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
# 按 user 消息切 submit
bounds = [i for i, x in enumerate(lines) if isinstance(x, dict) and x.get("role") == "user"]
print("user 消息位置:", bounds)
seg = []
for k, b in enumerate(bounds):
    e = bounds[k+1] if k+1 < len(bounds) else len(lines)
    asst = sum(1 for x in lines[b:e] if isinstance(x, dict) and x.get("role") == "assistant")
    tools = 0
    for x in lines[b:e]:
        if isinstance(x, dict) and x.get("role") == "assistant" and isinstance(x.get("content"), list):
            tools += sum(1 for bb in x["content"] if isinstance(bb, dict) and bb.get("type") == "tool_use")
    seg.append((b, e, asst, tools))
print()
print(f"{'submit':>6s} {'起':>5s} {'止':>5s} {'assistant':>9s} {'tool_use':>8s}")
for k, s in enumerate(seg):
    print(f"{k+1:6d} {s[0]:5d} {s[1]:5d} {s[2]:9d} {s[3]:8d}")
print()
# 最后 3 条 assistant 文本
txts = []
for x in lines:
    if isinstance(x, dict) and x.get("role") == "assistant":
        c = x.get("content")
        if isinstance(c, str) and c.strip(): txts.append(c.strip())
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text" and str(b.get("text","")).strip():
                    txts.append(str(b["text"]).strip())
print("assistant 文本条数:", len(txts))
for t in txts[-3:]:
    print("---", repr(t[:300]))
print()
# 工具结果：去掉第二段 rg 的输出后是否逐字节相同？
def result_of(i):
    for x in lines[i+1:i+6]:
        if not isinstance(x, dict): continue
        c = x.get("content")
        if isinstance(c, str) and c.strip(): return c
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    cc = b.get("content")
                    return cc if isinstance(cc, str) else json.dumps(cc, ensure_ascii=False)
    return None
calls = []
for i, x in enumerate(lines):
    if isinstance(x, dict) and x.get("role") == "assistant" and isinstance(x.get("content"), list):
        for b in x["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                calls.append((i, b.get("name")))
loop = calls[260:433]
pref = []
for i, n in loop:
    r = result_of(i)
    pref.append(r.split("=== GUI 面板口径 ===")[0] if r else "")
import collections
print("循环段工具调用:", len(loop))
print("结果『第一段 rg』前缀去重后种类数:", len(set(pref)))
c = collections.Counter(pref)
print("最常见前缀出现次数:", c.most_common(1)[0][1] if c else 0)
