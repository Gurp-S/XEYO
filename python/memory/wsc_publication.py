"""A head manifest binds complete head bytes, source version and cold objects."""
from __future__ import annotations
import ast
import re
import json
from pathlib import Path
from synaptic.contracts import digest, verify_object

_READ = re.compile(r"file_path=('(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\")")


def _legacy_paths(text):
    """Read compatibility only: old publications encoded ownership in text."""
    paths = set()
    for match in _READ.finditer(text):
        if ".v-sha256-" not in match.group(1):
            continue
        value = ast.literal_eval(match.group(1))
        if ".v-sha256-" in value:
            paths.add(value)
    return paths


def manifest(text, view_path, cwd, seal, lifecycle=None, *, evidence_paths=()):
    paths = set(evidence_paths)
    if view_path:
        paths.add(str(view_path))
    objects = {}
    for name in sorted(paths):
        if not name:
            continue
        path = Path(name)
        path = (path if path.is_absolute() else Path(cwd) / path).resolve()
        identity = verify_object(path)
        if not identity:
            raise ValueError("unsealed_view")
        objects[str(path)] = identity
    return {"version": 2, "head_sha256": digest(text.encode("utf-8")), "source_seal": seal,
            "lifecycle_sha256": digest(json.dumps(lifecycle or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")),
            "objects": objects}


def validate(rec):
    expected = rec.get("publication")
    if not expected:
        return False
    version = expected.get('version')
    if version not in (None, 2):
        return False
    paths = expected.get('objects', {}) if version == 2 else _legacy_paths(rec['text'])
    if version == 2 and not isinstance(paths, dict):
        return False
    actual = manifest(rec['text'], rec['view_path'], rec['cwd'], rec['seal'],
                      rec.get('lifecycle'), evidence_paths=paths)
    if version is None:
        actual.pop('version')
    return expected == actual
