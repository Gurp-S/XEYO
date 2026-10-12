"""Engine-owned output manifests. Presentation switches never own cleanup."""
import hashlib
import json
from pathlib import Path
import re
import time
import os
import tempfile
from functools import wraps


def _save(path, record):
    target = _manifest(path)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _locked(fn):
    @wraps(fn)
    def call(path, *args, **kwargs):
        from engine.write_transaction import path_lock
        with path_lock(str(_manifest(path))):
            return fn(path, *args, **kwargs)
    return call

_OWNED = re.compile(r"(?:bash-[0-9a-f]{32}|[0-9]{8}-[0-9]{6}-[0-9a-f]{8})\.txt\Z")


def _manifest(path):
    return Path(str(path) + ".xeyo-artifact.json")


@_locked
def register(path):
    path = Path(path)
    if not _OWNED.fullmatch(path.name) or path.is_symlink():
        raise ValueError("artifact_not_owned")
    data = path.read_bytes()
    record = {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "created_at": time.time(), "pins": []}
    _save(path, record)
    return record


def inspect(path):
    path = Path(path)
    try:
        record = json.loads(_manifest(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unknown"}
    if not path.is_file():
        return {**record, "status": "expired"}
    data = path.read_bytes()
    return {**record, "status": "available" if len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"] else "modified"}


@_locked
def pin(path, reference):
    record = inspect(path)
    if record.get("status") != "available":
        return False
    record.pop("status", None)
    record["pins"] = sorted(set(record["pins"]) | {reference})
    _save(path, record)
    return True


@_locked
def release(path, reference):
    record = inspect(path)
    if record.get("status") not in {"available", "modified"}:
        return False
    record.pop("status", None)
    record["pins"] = [item for item in record["pins"] if item != reference]
    _save(path, record)
    return True


@_locked
def _expire(path, root, cutoff, now):
    path = Path(path)
    manifest = _manifest(path)
    if manifest.is_symlink():
        return False
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("name") != path.name or not _OWNED.fullmatch(path.name):
        return False
    if record.get("pins") or record.get("expired_at") or record.get("created_at", 0) >= cutoff:
        return False
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        return False
    if inspect(path).get("status") not in {"available", "expired"}:
        return False
    path.unlink(missing_ok=True)
    record["expired_at"] = now
    _save(path, record)
    return True


def prune(root, *, days=7, now=None):
    root = Path(root).resolve()
    now = time.time() if now is None else now
    if days <= 0:
        return 0
    removed = 0
    for manifest in root.rglob("*.xeyo-artifact.json"):
        # Never follow an unowned manifest path before locking it.
        target = Path(str(manifest)[:-len(".xeyo-artifact.json")])
        if manifest.is_symlink() or not _OWNED.fullmatch(target.name) or not target.resolve().is_relative_to(root):
            continue
        try:
            removed += bool(_expire(target, root, now - days * 86400, now))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return removed
