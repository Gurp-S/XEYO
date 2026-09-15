# -*- coding: utf-8 -*-
"""验证 ⑥：InjectContext(multi_agent=True) → run_pre_llm_inject 挂上 multi_agent_hint。"""
import json, os, sys
sys.path.insert(0, r"D:\lea\XenYon code\python")
os.environ["XEYO_BENCH_MINIMAL"] = "1"
from prompt.pre_llm_inject import run_pre_llm_inject, InjectContext

def probe(ma: bool) -> str:
    projected = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "tool_call_id": "t1", "name": "Bash", "content": "ok"},
    ]
    ctx = InjectContext(multi_agent=ma)
    out = run_pre_llm_inject([json.loads(json.dumps(m)) for m in projected], ctx)
    return json.dumps(out, ensure_ascii=False)

off = probe(False)
on = probe(True)
print("multi_agent=False 命中提示:", "Multi-Agent" in off)
print("multi_agent=True  命中提示:", "Multi-Agent" in on)
print("True 时新增片段:", on.replace(off, "").strip()[:400] if "Multi-Agent" in on else "(无)")
