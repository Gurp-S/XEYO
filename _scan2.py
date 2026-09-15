import ast, pathlib, re

SKIP = re.compile(r"(^|[\\/])(tests|node_modules|\.venv|generated|localmodels|\.pytest|\.tmp|__pycache__)([\\/]|$)")
OBS = re.compile(r"^(observe|record|note|track|audit|log|emit)")
PROT = re.compile(r"(process|guard|deny|fold|block|limit|cap|clamp|reject|enforce|prune|drop|filter|resolve)")

def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        b = dotted(node.value)
        return f"{b}.{node.attr}" if b else node.attr
    return ""

def calls_in(nodes):
    out = []
    for n in nodes:
        for c in ast.walk(n):
            if isinstance(c, ast.Call):
                out.append((c.lineno, dotted(c.func)))
    return out

rows = []
for f in pathlib.Path("python").rglob("*.py"):
    s = str(f)
    if SKIP.search(s):
        continue
    try:
        tree = ast.parse(f.read_text(encoding="utf-8-sig"))
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        bc = calls_in(node.body)
        obs = [c for c in bc if OBS.match(c[1].split(".")[-1] or "")]
        prot = [c for c in bc if PROT.search(c[1].split(".")[-1] or "")]
        if obs and prot:
            rows.append((s, node.lineno, node.end_lineno,
                         sorted({c[1] for c in obs}), sorted({c[1] for c in prot})))
for r in sorted(rows):
    print(f"{r[0]}:{r[1]}-{r[2]}")
    print("   OBS :", ", ".join(r[3]))
    print("   PROT:", ", ".join(r[4]))
print("TOTAL", len(rows))
