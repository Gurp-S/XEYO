import ast, io
sites = [
 ("python/memory/observe.py",77),
 ("python/memory/runtime.py",237),
 ("python/memory/runtime.py",1182),
 ("python/memory/runtime.py",1570),
 ("python/permissions/bash_policy.py",409),
 ("python/permissions/store.py",163),
 ("python/permissions/store.py",348),
 ("python/permissions/store.py",395),
 ("python/permissions/workspace_policy.py",129),
 ("python/server/routers/chat.py",760),
]
for p,ln in sites:
    s=io.open(p,encoding="utf-8-sig").read().split(chr(10))
    print("==== %s:%d" % (p,ln))
    for i in range(ln-6, ln+6):
        if 0 <= i < len(s): print(i+1, s[i])
