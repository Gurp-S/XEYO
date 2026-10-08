"""Bounded mismatch facts and an optimistic base from validated exact content."""
from __future__ import annotations
import difflib
from engine.execution_facts import enabled


def mismatch(expected, observed):
    base = f"String to replace not found in file.\nString: {expected}"
    if not enabled():
        return base
    needle = expected.splitlines()
    lines = observed.splitlines()
    count = max(1, len(needle))
    best = None
    for i in range(min(len(lines), 2000)):
        candidate = "\n".join(lines[i:i + count])[:1000]
        score = difflib.SequenceMatcher(None, expected[:1000], candidate, autojunk=False).ratio()
        if best is None or score > best[0]:
            best = (score, i + 1, candidate)
    if best:
        base += f"\nnearest_line={best[1]}; expected={expected[:160]!r}; observed={best[2][:160]!r}"
    return base


def validated_base(tool):
    if not enabled():
        return ""
    text = getattr(tool, "_last_file_content", None)
    if text is None:
        return ""
    from tools.fileio.read_state import _content_hash_text
    return _content_hash_text(text)
