import ast, pathlib, re
SKIP = re.compile(r"(^|[\\/])(tests|node_modules|\.venv|generated|localmodels|\.pytest|\.tmp|__pycache__)([\\/]|$)")
OBS = re.compile(r"^(observe|record|note|audit|publish_advice|_audit)$|^(observe_|record_|note_|_note|log_)")
def dotted(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        b = dotted(node.value); return f"{b}.{node.attr}" if b else node.attr
    return ""
def calls_in(nodes):
    out = []
    for n in nodes:
        for c in ast.walk(n):
            if isinstance(c, ast.Call): out.append((c.lineno, dotted(c.func)))
    return out
def swallows(h):
    if not h:
        return False
    stmts = h.body
    if len(stmts) == 1 and isinstance(stmts[0], ast.Pass):
        return True
    return False
rows = []
for f in list(pathlib.Path("python/engine").rglob("*.py")) + list(pathlib.Path("python/tools").rglob("*.py")):
    s = str(f)
    if SKIP.search(s): continue
    try: tree = ast.parse(f.read_text(encoding="utf-8-sig"))
    except Exception: continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try): continue
        if not swallows(node.handlers[0] if node.handlers else None): continue
        bc = calls_in(node.body)
        obs = sorted({c[1] for c in bc if OBS.match(c[1].split(".")[-1] or "")})
        other = sorted({c[1] for c in bc if c[1] and not OBS.match(c[1].split(".")[-1] or "")})
        if obs and other:
            rows.append((s, node.lineno, node.end_lineno, obs, other))
for r in sorted(rows):
    print(f"{r[0]}:{r[1]}-{r[2]}")
    print("   OBS :", ", ".join(r[3]))
    print("   OTH :", ", ".join(r[4]))
print("TOTAL", len(rows))
