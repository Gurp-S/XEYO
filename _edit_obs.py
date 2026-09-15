import ast, pathlib, re

SKIP = re.compile(r"(^|[\\/])(tests|node_modules|\.venv|generated|localmodels|\.pytest|\.tmp|__pycache__)([\\/]|$)")
OBS = re.compile(r"^(observe|record|note|audit|publish_advice)|^(observe_|record_|note_|log_|_record|_note)")
DIRS = ["python/engine", "python/tools"]


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        base = dotted(node.func)
        return f"{base}()" if base else ""
    return ""


def short(name):
    return name.split(".")[-1].rstrip("()")


def obs_calls(nodes):
    out = []
    for n in nodes:
        for c in ast.walk(n):
            if isinstance(c, ast.Call) and OBS.match(short(dotted(c.func))):
                out.append((c.lineno, dotted(c.func)))
    return sorted(out)


def bare_pass(handler):
    return len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)


def ensure_logging_import(text, lines):
    if re.search(r"^import logging$", text, re.M):
        return lines
    # find contiguous stdlib `import X` lines after the future import
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("from __future__ import ") or ln.startswith("from __future__"):
            start = i
            break
    if start is None:
        start = -1
    block = []
    i = start + 1
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("import ") and not ln.startswith("import (") and " as " not in ln:
            block.append(i)
            i += 1
        elif ln == "" and not block:
            i += 1
        else:
            break
    if not block:
        # fall back: after future import + blank
        insert_at = start + 2 if start >= 0 else 0
    else:
        insert_at = None
        for idx in block:
            if lines[idx].strip() > "import logging":
                insert_at = idx
                break
        if insert_at is None:
            insert_at = block[-1] + 1
    lines.insert(insert_at, "import logging\n")
    return lines


changed = []
for d in DIRS:
    for f in pathlib.Path(d).rglob("*.py"):
        s = str(f)
        if SKIP.search(s):
            continue
        text = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except Exception as e:
            print("PARSE FAIL", s, e)
            continue
        targets = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            handlers = [h for h in node.handlers if bare_pass(h)]
            if not handlers:
                continue
            obs = obs_calls(node.body)
            if not obs:
                continue
            label = obs[0][1]
            targets.append((handlers[0].body[0].lineno, handlers[0].body[0].col_offset, label))
        if not targets:
            continue
        lines = text.splitlines(keepends=True)
        for lineno, col, label in sorted(targets, reverse=True):
            indent = lines[lineno - 1][:col]
            lines[lineno - 1] = (
                f'{indent}logging.getLogger(__name__).debug("{label} failed", exc_info=True)\n'
            )
        lines = ensure_logging_import("".join(lines), lines)
        f.write_text("".join(lines), encoding="utf-8")
        changed.append((s, len(targets)))

for s, n in changed:
    print(f"patched {n:2d}  {s}")
print("FILES", len(changed))
