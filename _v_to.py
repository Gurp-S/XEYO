import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
root = r"D:\lea\XenYon code\TerminalBench\.venv-harbor313\Lib\site-packages\harbor"
hits = {}
for dirpath, dirs, files in os.walk(root):
    if "__pycache__" in dirpath:
        continue
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        try:
            s = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for pat in ("verifier_timeout_multiplier", "agent_timeout_multiplier", "timeout_multiplier"):
            for m in re.finditer(pat + r'[^\n]{0,80}', s):
                hits.setdefault(pat, []).append(f"{os.path.relpath(p, root)}:{s[:m.start()].count(chr(10))+1}: {m.group(0)[:100]}")
for pat in ("verifier_timeout_multiplier", "agent_timeout_multiplier", "timeout_multiplier"):
    print("=" * 20, pat)
    for h in (hits.get(pat) or [])[:14]:
        print("  ", h)
