import ast, io, os

ROOTS = ["python"]

def is_pass_only(body):
    stmts = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
    return len(stmts) == 1 and isinstance(stmts[0], ast.Pass)

hits = []
for root in ROOTS:
    for dp, dn, fn in os.walk(root):
        if any(x in dp for x in ("__pycache__", ".venv", "node_modules", "generated")):
            continue
        for f in fn:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            try:
                src = io.open(p, encoding="utf-8-sig").read()
                tree = ast.parse(src)
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if is_pass_only(node.body):
                        hits.append((p, node.lineno))
print("TOTAL", len(hits))
for p, ln in hits:
    print(f"{p}:{ln}")
