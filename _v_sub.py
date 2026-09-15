import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
for p in ("python/engine/subagent_runner.py", "python/tools/container_routing.py"):
    s = open(p, encoding="utf-8").read()
    print("=" * 25, p, len(s))
    for m in re.finditer(r"(Thread|create_task|to_thread|run_in_executor|ContextVar|copy_context|set_container_override|get_container_override|contextvars)[^\n]{0,90}", s):
        line = s[:m.start()].count("\n") + 1
        print(f"  {line}: {m.group(0)[:110]}")
