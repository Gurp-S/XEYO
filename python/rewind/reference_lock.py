"""Cross-process lock for snapshot publication and reference-journal changes.

Publishers hold this lock from blob creation through the durable journal append.
Blob GC holds it across reference scanning and deletion. The lock is keyed by the
snapshot root so custom roots used by isolated sessions remain independent.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from engine.write_transaction import path_lock


_STATE = threading.local()


def _root(snapshot_root: Path | str | None = None) -> Path:
    if snapshot_root is not None:
        return Path(snapshot_root).expanduser()
    override = os.environ.get("XEYO_SNAPSHOTS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "snapshots"


@contextmanager
def reference_publication_lock(
    snapshot_root: Path | str | None = None,
) -> Iterator[None]:
    """Serialize one snapshot root's publishers with blob GC, reentrantly."""

    root = _root(snapshot_root)
    lock_path = root / ".reference-publication"
    key = os.path.normcase(os.path.realpath(lock_path))
    held: dict[str, int] = getattr(_STATE, "held", {})
    depth = held.get(key, 0)
    if depth:
        held[key] = depth + 1
        try:
            yield
        finally:
            held[key] -= 1
        return

    with path_lock(str(lock_path)):
        held[key] = 1
        _STATE.held = held
        try:
            yield
        finally:
            held.pop(key, None)


__all__ = ["reference_publication_lock"]
