import ast, os
OBS = ("observe","ledger","record","audit","track","emit","metric","telemetry","snapshot","calibrat")
GUARD = ("process","guard","fold","deny","enforce","block","stop","reject","clamp","cap","limit","protect","shrink","truncat","prune")
def names(node):
    out=set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f=n.func
            if isinstance(f, ast.Name): out.add(f.id)
            elif isinstance(f, ast.Attribute): out.add(f.attr)
    return out
for dp,_,fs in os.walk("."):
    if ".venv" in dp or "tests" in dp or "__pycache__" in dp: continue
    for fn in fs:
        if not fn.endswith(".py"): continue
        p=os.path.join(dp,fn)
        try: tree=ast.parse(open(p,encoding="utf-8").read())
        except Exception: continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try): continue
            ns=set()
            for s in node.body: ns|=names(s)
            obs={x for x in ns if any(k in x.lower() for k in OBS)}
            gd={x for x in ns if any(k in x.lower() for k in GUARD)}
            if obs and gd:
                print(f"{p}:{node.lineno} OBS={sorted(obs)} GUARD={sorted(gd)}")
