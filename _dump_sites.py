import ast, io
sites = [
 ("python/extension/config.py",117),
 ("python/extension/mcp_client.py",1136),
 ("python/extension/mcp_manager.py",320),
 ("python/extension/mcp_scopes.py",261),
 ("python/memory/agent_scope.py",310),
 ("python/memory/observe.py",77),
 ("python/memory/runtime.py",237),
 ("python/memory/runtime.py",1182),
 ("python/memory/runtime.py",1570),
 ("python/memory/runtime.py",1594),
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
    for i in range(ln-8, ln+4):
        if 0 <= i < len(s): print(i+1, s[i])
