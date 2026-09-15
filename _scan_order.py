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

def meaningful(stmts):
    return [s for s in stmts if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]

rows = []
for dp, dn, fn in os.walk(ROOT):
    if any(x in dp for x in ("__pycache__", ".venv", "node_modules", "generated")):
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
            body = meaningful(node.body)
            # classify each top-level stmt
            cls = []
            for s in body:
                if isinstance(s, (ast.Import, ast.ImportFrom)):
                    cls.append(("import", s))
                    continue
                names = stmt_calls(s)
                if names and all(is_obs_name(n) for n in names):
                    cls.append(("obs", s))
                else:
                    cls.append(("act", s))
            # find obs-before-act
            seen_obs = False
            flagged = False
            for kind, s in cls:
                if kind == "obs":
                    seen_obs = True
                elif kind == "act" and seen_obs:
                    flagged = True
            if flagged:
                # check except swallows
                swallow = any(
                    len([x for x in h.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]) == 1
                    and isinstance([x for x in h.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))][0], ast.Pass)
                    for h in node.handlers
                )
                rows.append((p, node.lineno, swallow))
print("OBS_BEFORE_ACT_TOTAL", len(rows))
for p, ln, sw in rows:
    print(f"{p}:{ln} swallow={sw}")
