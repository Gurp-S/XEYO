import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
root = r"D:\lea\XenYon code\TerminalBench\.venv-harbor313\Lib\site-packages\harbor"
pats = (r'"(cancel|pause|resume|stop|interrupt)"', r"def (cancel|pause|resume|stop)\b", r"cancel_event|stop_event|should_stop|abort_event")
for dp, dn, fs in os.walk(root):
    if "__pycache__" in dp: continue
    for f in fs:
        if not f.endswith(".py"): continue
        p = os.path.join(dp, f)
        s = open(p, encoding="utf-8", errors="replace").read()
        for pat in pats:
            for m in re.finditer(pat, s):
                ln = s[:m.start()].count(chr(10)) + 1
                print(f"{os.path.relpath(p, root)}:{ln}: {s.splitlines()[ln-1].strip()[:130]}")
