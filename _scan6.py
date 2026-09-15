import ast, pathlib, re
SKIP = re.compile(r"(^|[\\/])(tests|node_modules|\.venv|generated|localmodels|\.pytest|\.tmp|__pycache__)([\\/]|$)")
PURE = {
 "str","int","float","bool","list","dict","set","tuple","len","type","getattr","setattr","hasattr",
 "max","min","any","all","next","reversed","sorted","range","enumerate","zip","isinstance","repr",
 "format","abs","round","sum","map","filter","frozenset","bytes","super","print","open","id","hash",
}
OBS = re.compile(r"^(observe|record|note|audit|_audit|publish_advice|_note)|^(observe_|record_|note_|log_|_log|_record|_note)")
def dotted(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        b = dotted(node.value); return f"{b}.{node.attr}" if b else node.attr
    return ""
def short(name):
    return name.split(".")[-1]
def calls_in(nodes):
    out = []
    for n in nodes:
        for c in ast.walk(n):
            if isinstance(c, ast.Call): out.append((c.lineno, dotted(c.func)))
    return out
def swallows(h):
    return bool(h) and len(h.body) == 1 and isinstance(h.body[0], ast.Pass)
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
        obs = sorted({c[1] for c in bc if OBS.match(short(c[1]))})
        other = sorted({c[1] for c in bc if c[1] and short(c[1]) not in PURE and not OBS.match(short(c[1]))})
        if obs and other:
            rows.append((s, node.lineno, node.end_lineno, obs, other))
for r in sorted(rows):
    print(f"{r[0]}:{r[1]}-{r[2]}")
    print("   OBS :", ", ".join(r[3]))
    print("   OTH :", ", ".join(r[4]))
print("TOTAL", len(rows))
