import ast, pathlib, re
SKIP = re.compile(r"(^|[\\/])(tests|node_modules|\.venv|generated|localmodels|\.pytest|\.tmp|__pycache__)([\\/]|$)")
OBS = re.compile(r"^(observe|record|note|audit|publish_advice)|^(observe_|record_|note_|log_|_record|_note)")
def dotted(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        b = dotted(node.value); return f"{b}.{node.attr}" if b else node.attr
    return ""
def short(n): return n.split(".")[-1]
def calls_in(nodes):
    out = []
    for n in nodes:
        for c in ast.walk(n):
            if isinstance(c, ast.Call): out.append((c.lineno, dotted(c.func)))
    return out
def bare_pass(h):
    return bool(h) and len(h.body) == 1 and isinstance(h.body[0], ast.Pass)
rows = []
for f in list(pathlib.Path("python/engine").rglob("*.py")) + list(pathlib.Path("python/tools").rglob("*.py")):
    s = str(f)
    if SKIP.search(s): continue
    try: tree = ast.parse(f.read_text(encoding="utf-8-sig"))
    except Exception: continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try): continue
        if not node.handlers: continue
        if not any(bare_pass(h) for h in node.handlers): continue
        obs = sorted({c[1] for c in calls_in(node.body) if OBS.match(short(c[1]))})
        if obs:
            rows.append((s, node.lineno, node.end_lineno, obs))
for r in sorted(rows):
    print(f"{r[0]}:{r[1]}-{r[2]}  OBS={r[3]}")
print("TOTAL", len(rows))
