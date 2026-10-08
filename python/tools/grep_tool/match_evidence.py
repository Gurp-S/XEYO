"""Bounded native match excerpts; no reimplementation of regex semantics."""
import json
import os
import re

from synaptic.task_checkpoint import enabled


def collect(input_data, args, target, cwd, runner, column_limit=500):
    if not enabled() or input_data.output_mode != "matches" or input_data.multiline:
        return None
    if any(getattr(input_data, name) is not None for name in ("context", "context_before", "context_after", "context_c")):
        return None
    # Preserve the producer's regex, timeout, backend and cancellation errors.
    lines = runner([*args, "--only-matching", "--column", "--with-filename", "-n"], target)
    records = []
    for line in lines:
        if "\0" not in line:
            return None
        path, payload = line.split("\0", 1)
        match = re.match(r"(\d+):(\d+):(.*)$", payload, re.S)
        if not match:
            return None
        text = match.group(3)
        if not text:
            continue
        try:
            relative = os.path.relpath(path, cwd)
        except ValueError:
            relative = path
        records.append({"format": "match_excerpt", "file": relative, "line": int(match.group(1)),
            "byte_column": int(match.group(2)), "text": text, "text_complete": len(text) <= column_limit})
    # Empty only-matching output may be a zero-width match, not zero hits.
    if not records:
        return []
    records.sort(key=lambda record: (record["file"].replace("\\", "/").casefold(), record["line"], record["byte_column"]))
    return records


def render(records):
    return "\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records)
