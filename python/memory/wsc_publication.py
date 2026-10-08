"""A head manifest binds complete head bytes, source version and cold objects."""
from __future__ import annotations
import ast
import re
import json
from pathlib import Path
from synaptic.contracts import digest, verify_object

_READ = re.compile(r"file_path=('(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\")")


def manifest(text, view_path, cwd, seal, lifecycle=None):
    paths = {str(view_path)} if view_path else set()
    for match in _READ.finditer(text):
        if ".v-sha256-" not in match.group(1):
            continue
        value = ast.literal_eval(match.group(1))
        if ".v-sha256-" in value:
            path = Path(value)
            paths.add(str(path if path.is_absolute() else Path(cwd) / path))
    objects = {}
    for name in sorted(paths):
        if not name:
            continue
        path = Path(name).resolve()
        identity = verify_object(path)
        if not identity:
            raise ValueError("unsealed_view")
        objects[str(path)] = identity
    return {"head_sha256": digest(text.encode("utf-8")), "source_seal": seal,
            "lifecycle_sha256": digest(json.dumps(lifecycle or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")),
            "objects": objects}


def validate(rec):
    expected = rec.get("publication")
    if not expected:
        return False
    return expected == manifest(rec["text"], rec["view_path"], rec["cwd"], rec["seal"], rec.get("lifecycle"))
