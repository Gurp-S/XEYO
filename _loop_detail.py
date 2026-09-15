# -*- coding: utf-8 -*-
import json, os
from collections import Counter, OrderedDict
from pathlib import Path

p = Path(os.path.expanduser("~")) / ".xeyo" / "sessions" / "sess_mu0mkitk_5aehjt.jsonl"
lines = [json.loads(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
print("消息条数:", len(lines))
print("角色分布:", Counter(x.get("role") for x in lines if isinstance(x, dict)))
print()

# 按顺序取工具调用 + 紧随其后的 tool result
seq = []
for i, x in enumerate(lines):
    if not isinstance(x, dict): continue
    c = x.get("content")
    if x.get("role") == "assistant" and isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                seq.append({"i": i, "name": b.get("name"), "id": b.get("id"),
                            "input": json.dumps(b.get("input"), sort_keys=True, ensure_ascii=False)})
print("工具调用总数:", len(seq))
key = [f'{s["name"]}|{s["input"][:300]}' for s in seq]
cnt = Counter(key)
print()
print("== 重复最多的 5 个签名 ==")
for k, n in cnt.most_common(5):
    print(f"  x{n}  {k[:220]}")

# 找那段重复区间的边界
top = cnt.most_common(1)[0][0]
idx = [j for j, k in enumerate(key) if k == top]
print()
print(f"重复段：第 {idx[0]}~{idx[-1]} 次调用（共 {len(idx)} 次），会话工具调用总 {len(seq)}")
print("重复段之前 3 次调用:", [f'{seq[j]["name"]}|{seq[j]["input"][:80]}' for j in range(max(0,idx[0]-3), idx[0])])
print("重复段之后 3 次调用:", [f'{seq[j]["name"]}|{seq[j]["input"][:80]}' for j in range(idx[-1]+1, min(len(seq), idx[-1]+4))])

# 取该签名前 3 次与第 160 次的 tool_result 内容，比较是否逐字节相同
def result_after(call_i):
    for x in lines[call_i+1:call_i+6]:
        if not isinstance(x, dict): continue
        c = x.get("content")
        if isinstance(c, str) and c.strip(): return c
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    cc = b.get("content")
                    return cc if isinstance(cc, str) else json.dumps(cc, ensure_ascii=False)
    return None

print()
for rank in (0, 1, 2, 100, len(idx)-1):
    if rank >= len(idx): continue
    j = idx[rank]
    r = result_after(seq[j]["i"])
    print(f"--- 第 {rank+1} 次重复调用（seq#{j}）结果的 sha1/size: ", end="")
    if r is None:
        print("None")
    else:
        import hashlib
        print(hashlib.sha1(r.encode()).hexdigest()[:12], len(r), "|", repr(r[:150]))
