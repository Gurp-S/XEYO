import io
# agent_scope.py
p = "python/memory/agent_scope.py"
lines = io.open(p, encoding="utf-8", newline="").read().split("\n")
def rm(lines, val, after_line=None):
    for i, l in enumerate(lines):
        if l.rstrip("\r") == val and (after_line is None or i > after_line):
            del lines[i]; return i
    raise SystemExit("not found " + val)
# remove misplaced
rm(lines, "import logging")
# find future line
fi = next(i for i,l in enumerate(lines) if l.startswith("from __future__ import"))
lines.insert(fi+2, "import logging\r")
io.open(p, "w", encoding="utf-8", newline="").write("\n".join(lines))
print("fixed", p)

p = "python/memory/runtime.py"
lines = io.open(p, encoding="utf-8", newline="").read().split("\n")
rm(lines, "import logging")
# insert after 'import json'
ji = next(i for i,l in enumerate(lines) if l.rstrip("\r") == "import json")
lines.insert(ji+1, "import logging\r")
io.open(p, "w", encoding="utf-8", newline="").write("\n".join(lines))
print("fixed", p)
