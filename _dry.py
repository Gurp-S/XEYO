import ast, io

SITES = [
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
 ("python/memory/runtime.py",1634),
 ("python/memory/runtime.py",1660),
 ("python/memory/runtime.py",1681),
 ("python/memory/runtime.py",1935),
 ("python/permissions/bash_policy.py",409),
 ("python/permissions/store.py",163),
 ("python/permissions/store.py",348),
 ("python/permissions/store.py",395),
 ("python/permissions/workspace_policy.py",129),
 ("python/server/routers/chat.py",760),
]

def pass_only(body):
    b=[s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
    return len(b)==1 and isinstance(b[0], ast.Pass)

for path, tline in SITES:
    text = io.open(path, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    tree = ast.parse(text)
    hit = [n for n in ast.walk(tree) if isinstance(n, ast.Try) and n.lineno == tline]
    assert len(hit)==1, (path, tline, len(hit))
    node = hit[0]
    hs = [h for h in node.handlers if pass_only(h.body)]
    print(f"{path}:{tline} handlers={len(node.handlers)} pass_handlers={len(hs)}")
    for h in hs:
        p = h.body[0]
        ln = p.lineno; col = p.col_offset
        content = lines[ln-1].rstrip("\r")
        print(f"    pass at line {ln} col {col}: {content!r} maxline={p.end_lineno}")
