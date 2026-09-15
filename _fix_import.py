import io, re

FILES = ["python/extension/config.py","python/memory/agent_scope.py","python/memory/observe.py","python/permissions/store.py"]

def norm(l): return l.rstrip("\r")

for path in FILES:
    text = io.open(path, encoding="utf-8", newline="").read()
    crlf = "\r\n" in text
    lines = text.split("\n")
    # find __future__ line
    fi = None
    for i, l in enumerate(lines):
        if norm(l).startswith("from __future__ import"):
            fi = i
    assert fi is not None, path
    # remove inserted logging line right after future
    j = fi + 1
    if norm(lines[j]) == "import logging":
        del lines[j]
    # now find the stdlib plain-import block: first contiguous run of 'import '/'from ' after future
    k = fi + 1
    # skip blanks
    while k < len(lines) and lines[k].strip() == "":
        k += 1
    block_start = k
    block_end = k
    while block_end < len(lines) and (lines[block_end].startswith("import ") or lines[block_end].startswith("from ")):
        block_end += 1
    # insert logging in sorted order among plain 'import ' lines
    ins = None
    for m in range(block_start, block_end):
        s = norm(lines[m])
        if s.startswith("import "):
            name = s[len("import "):].strip()
            if name > "logging" and ins is None:
                ins = m
    if ins is None:
        # place after last plain import
        ins = block_end
        for m in range(block_end - 1, block_start - 1, -1):
            if norm(lines[m]).startswith("import "):
                ins = m + 1
                break
    lines.insert(ins, "import logging\r" if crlf else "import logging")
    io.open(path, "w", encoding="utf-8", newline="").write("\n".join(lines))
    print("fixed", path)
