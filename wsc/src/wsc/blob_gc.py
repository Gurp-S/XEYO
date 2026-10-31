"""Reference-aware blob GC: a content-addressed object survives only while a
result row (or a caller-declared live hash) still names it.

The result store's rows and blobs are a rebuildable index; a crash may leave an
unreferenced blob, never a committed reference.  This module is the collector
for that surplus: it computes reachability first, then removes the difference,
one file at a time, so an interrupted run leaves a smaller surplus and a repeat
run finishes the job.
"""
import time
from pathlib import Path

# A capture writes one dot-prefixed temp file, then links it into place.  A
# killed writer leaves that file behind; it is never referenced by a row, so the
# only question is whether a concurrent writer may still be using it.
TEMP_GLOB = ".*.tmp"
TEMP_AGE_SECONDS = 300


def stale_temps(store, *, age_seconds=TEMP_AGE_SECONDS, now=None) -> list:
    """Temp files old enough that no live writer can still own them."""
    now = time.time() if now is None else now
    return sorted(path for path in Path(store.objects).glob(TEMP_GLOB)
                  if now - path.stat().st_mtime >= age_seconds)


def reachable(store, keep_hashes=()) -> set:
    with store.connect() as db:
        stored = {row[0] for row in db.execute(
            "SELECT DISTINCT hash FROM results WHERE hash IS NOT NULL").fetchall()}
    return stored | {value for value in keep_hashes if value}


def orphans(store, *, keep_hashes=()) -> list:
    keep = reachable(store, keep_hashes)
    return sorted(path for path in Path(store.objects).glob("*.txt") if path.stem not in keep)


def collect(store, *, keep_hashes=(), dry_run=True, temp_age_seconds=TEMP_AGE_SECONDS) -> dict:
    found = orphans(store, keep_hashes=keep_hashes)
    temps = stale_temps(store, age_seconds=temp_age_seconds)
    removed, temp_removed = [], []
    if not dry_run:
        for path in found:
            path.unlink(missing_ok=True)
            removed.append(path.name)
        for path in temps:
            path.unlink(missing_ok=True)
            temp_removed.append(path.name)
    return {"orphans": [path.name for path in found], "removed": removed,
            "temp_orphans": [path.name for path in temps], "temp_removed": temp_removed}


def live_hashes(store, *, call_ids=(), result_ids=()) -> set:
    """Hashes a durable operation still owns, resolved from its identifiers.

    Open intents store a result id (or only a call id when the blob was staged
    but never linked), so the collector is handed those identifiers rather than
    raw hashes and resolves them here.
    """
    ids = {str(value) for value in result_ids if value is not None}
    calls = {str(value) for value in call_ids if value is not None}
    found = set()
    if not ids and not calls:
        return found
    with store.connect() as db:
        if ids:
            marks = ",".join("?" * len(ids))
            found |= {row[0] for row in db.execute(
                "SELECT hash FROM results WHERE hash IS NOT NULL AND "
                f"(CAST(id AS TEXT) IN ({marks}) OR call_id IN ({marks}))",
                tuple(ids) * 2).fetchall()}
        if calls:
            marks = ",".join("?" * len(calls))
            found |= {row[0] for row in db.execute(
                "SELECT hash FROM results WHERE hash IS NOT NULL AND "
                f"call_id IN ({marks})", tuple(calls)).fetchall()}
    return found