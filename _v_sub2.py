import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
for p in ("python/tools/agent_tool/agent_tool.py", "python/engine/subagent_runner.py"):
    s = open(p, encoding="utf-8").read()
    print("=" * 25, p)
    for m in re.finditer(r"(import threading|Thread\(|create_task|asyncio\.|run_subagent|def (run|execute|spawn|_run)[a-z_]*\()", s):
        line = s[:m.start()].count("\n") + 1
        print(f"  {line}: {s.splitlines()[line-1].strip()[:120]}")
