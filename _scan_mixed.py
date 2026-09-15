import ast, io, os

ROOT = "python"
OBS_PREFIX = ("observe", "record", "note", "audit", "track", "metric", "telemetry", "emit_", "sample")

def call_name(node):
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute):
            return f.attr
        if isinstance(f, ast.Name):
            return f.id
    return None

def stmt_calls(stmt):
    return [call_name(n) for n in ast.walk(stmt) if isinstance(n, ast.Call)]

def is_obs_name(nm):
    return nm is not None and nm.lower().startswith(OBS_PREFIX)

rows = []
for dp, dn, fn in os.walk(ROOT):
    if any(x in dp for x in ("__pycache__", ".venv", "node_modules", "generated", os.sep + "tests")):
        continue
    for f in fn:
        if not f.endswith(".py"):
            continue
        p = os.path.join(dp, f)
        try:
            tree = ast.parse(io.open(p, encoding="utf-8-sig").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            swallows = False
            for h in node.handlers:
                b = [s for s in h.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
                if len(b) == 1 and isinstance(b[0], ast.Pass):
                    swallows = True
            if not swallows:
                continue
            obs_stmts, other_stmts = [], []
            for s in node.body:
                names = stmt_calls(s)
                if names and all(is_obs_name(n) for n in names):
                    obs_stmts.append(s)
                else:
                    other_stmts.append(s)
            if obs_stmts and other_stmts:
                rows.append((p, node.lineno, [call_name(n) for s in obs_stmts for n in ast.walk(s) if isinstance(n, ast.Call)]))
print("MIXED_TOTAL", len(rows))
for p, ln, names in rows:
    print(f"{p}:{ln}  obs={names}")
