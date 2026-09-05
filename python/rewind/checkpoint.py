"""Checkpoint helpers for Rewind v2 (Cursor-aligned).

A checkpoint_id is a stable, content-addressable id bound to a user message's
pre-agent workspace snapshot (shadow commit).  Turn end may cache shadow_paths
so Restore Checkpoint skips a full diff scan.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from session.persistence import default_sessions_dir, safe_session_filename


def derive_checkpoint_id(*, session_id: str, user_message_id: str, before_commit: str) -> str:
    """Stable id from session + user message + shadow commit."""
    raw = f"{session_id}\0{user_message_id}\0{before_commit}".encode("utf-8")
    return f"cp_{hashlib.sha256(raw).hexdigest()[:24]}"


def _cache_path(session_id: str, sessions_dir: Path | None = None) -> Path:
    root = sessions_dir or default_sessions_dir()
    return root / safe_session_filename(session_id) / "checkpoint_cache.jsonl"


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(session_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[session_id] = lock
        return lock


def put_checkpoint_cache(
    session_id: str,
    *,
    checkpoint_id: str,
    user_message_id: str,
    before_commit: str,
    shadow_paths: list[str] | None = None,
    fingerprint_paths: list[str] | None = None,
    sessions_dir: Path | None = None,
) -> None:
    """Append one checkpoint cache row (latest wins for same checkpoint_id)."""
    path = _cache_path(session_id, sessions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "checkpoint_id": checkpoint_id,
        "user_message_id": user_message_id,
        "before_commit": before_commit,
        "shadow_paths": list(shadow_paths or []),
        "fingerprint_paths": list(fingerprint_paths or []),
        "cached_at": time.time(),
    }
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock_for(session_id):
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()


def get_checkpoint_cache(
    session_id: str,
    *,
    checkpoint_id: str | None = None,
    user_message_id: str | None = None,
    sessions_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Return latest matching cache row, or None."""
    path = _cache_path(session_id, sessions_dir)
    if not path.is_file():
        return None
    cp = (checkpoint_id or "").strip()
    mid = (user_message_id or "").strip()
    if not cp and not mid:
        return None
    latest: dict[str, Any] | None = None
    with _lock_for(session_id):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if cp and str(row.get("checkpoint_id") or "") != cp:
            continue
        if mid and str(row.get("user_message_id") or "") != mid:
            continue
        latest = row
    return latest


__all__ = [
    "derive_checkpoint_id",
    "get_checkpoint_cache",
    "put_checkpoint_cache",
]
