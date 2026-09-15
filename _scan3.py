import ast, pathlib, re
files = list(pathlib.Path("python").rglob("*.py"))
print("files:", len(files))
ok = 0
tries = 0
for f in files:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"))
    except Exception as e:
        print("parse fail", f, e)
        continue
    ok += 1
    tries += sum(1 for n in ast.walk(tree) if isinstance(n, ast.Try))
print("parsed:", ok, "tries:", tries)
