import ast, io, os
ROOT = "python"
OBS_PREFIX = ("observe","record","note","audit","track","metric","telemetry","sample","emit_")
def call_name(node):
    if isinstance(node, ast.Call):
        f=node.func
        if isinstance(f, ast.Attribute): return f.attr
        if isinstance(f, ast.Name): return f.id
    return None
def is_obs(nm): return nm is not None and nm.lower().startswith(OBS_PREFIX)
def pass_only(body):
    b=[s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return len(b)==1 and isinstance(b[0], ast.Pass)
def meaningful(body):
    return [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
rows=[]
for dp,dn,fn in os.walk(ROOT):
    if any(x in dp for x in ("__pycache__",".venv","node_modules","generated")): continue
    for f in fn:
        if not f.endswith(".py"): continue
        p=os.path.join(dp,f)
        if "test" in f or os.sep+"tests" in dp: continue
        try: tree=ast.parse(io.open(p,encoding="utf-8-sig").read())
        except Exception: continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Try) and any(pass_only(h.body) for h in node.handlers)): continue
            # purely observation try?
            pure=True
            for s in meaningful(node.body):
                if isinstance(s,(ast.Import,ast.ImportFrom)): continue
                names=[call_name(n) for n in ast.walk(s) if isinstance(n, ast.Call)]
                if not names or not all(is_obs(n) for n in names):
                    pure=False; break
            if pure:
                obs=[call_name(n) for s in node.body for n in ast.walk(s) if isinstance(n,ast.Call)]
                rows.append((p,node.lineno,obs))
print("PURE_OBS_BAREPASS_TOTAL", len(rows))
for p,ln,n in rows: print(f"{p}:{ln} {n}")
