import ast, io

# (path, try_lineno, label)
SITES = [
 ("python/extension/config.py",117,"config.invalid audit failed"),
 ("python/extension/mcp_client.py",1136,"mcp.tool.call audit failed"),
 ("python/extension/mcp_manager.py",320,"mcp.server.failed audit failed"),
 ("python/extension/mcp_scopes.py",261,"enterprise policy invalid audit failed"),
 ("python/memory/agent_scope.py",310,"subagent transcript flush failed"),
 ("python/memory/observe.py",77,"calibration observe failed"),
 ("python/memory/runtime.py",237,"memory.aging.advance audit failed"),
 ("python/memory/runtime.py",1182,"projection digest note failed"),
 ("python/memory/runtime.py",1570,"c2 formula path failed; falling back to decide"),
 ("python/memory/runtime.py",1594,"record_c2_event failed"),
 ("python/memory/runtime.py",1634,"record_c2_event failed"),
 ("python/memory/runtime.py",1660,"record_c2_event failed"),
 ("python/memory/runtime.py",1681,"record_c2_event failed"),
 ("python/memory/runtime.py",1935,"record_c2_event failed"),
 ("python/permissions/bash_policy.py",409,"bash_rules.invalid audit failed"),
 ("python/permissions/store.py",163,"permission.resolved audit failed"),
 ("python/permissions/store.py",348,"permission.grant.added audit failed"),
 ("python/permissions/store.py",395,"permission.grant.revoked audit failed"),
 ("python/permissions/workspace_policy.py",129,"policy.invalid audit failed"),
 ("python/server/routers/chat.py",760,"note_request_env failed"),
]

def pass_only(body):
    b=[s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
    return len(b)==1 and isinstance(b[0], ast.Pass)

def has_import_logging(tree):
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "logging":
                    return True
    return False

def insert_import_logging(lines):
    # find insertion index
    idx = 0
    # module docstring
    src = "\n".join(l.rstrip("\r") for l in lines)
    tree = ast.parse(src)
    body = tree.body
    pos = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        pos = body[0].end_lineno
        idx = pos
    end = None
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            end = n.end_lineno
    if end is not None:
        idx = end
    lines.insert(idx, "import logging\r" if (idx>0 and lines and lines[0].endswith("\r")) else "import logging")
    return lines

by_file = {}
for p,t,l in SITES:
    by_file.setdefault(p, []).append((t,l))

for path, items in by_file.items():
    text = io.open(path, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    tree = ast.parse(text)
    for tline, label in items:
        node = [n for n in ast.walk(tree) if isinstance(n, ast.Try) and n.lineno == tline]
        assert len(node)==1, (path, tline)
        hs = [h for h in node[0].handlers if pass_only(h.body)]
        assert len(hs)==1, (path, tline, len(hs))
        pnode = hs[0].body[0]
        idx = pnode.lineno - 1
        content = lines[idx]
        eol = "\r" if content.endswith("\r") else ""
        core = content[:-1] if eol else content
        indent = core[: len(core) - len(core.lstrip())]
        new = indent + 'logging.getLogger(__name__).debug("%s", exc_info=True)' % label
        lines[idx] = new + eol
    text = "\n".join(lines)
    tree = ast.parse(text)
    if not has_import_logging(tree):
        lines = insert_import_logging(lines)
        text = "\n".join(lines)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("edited", path, len(items), "sites")
