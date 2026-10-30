"""Source binding checks shared by preparation and publication."""
import json

from . import events
from .contracts import Snapshot, digest, require
from .store import getmeta


def semantic_writes_allowed(db):
    require(getmeta(db, "mode") == "active", "component_not_active")
    require(not db.execute("SELECT 1 FROM operations WHERE kind='detach' AND state IN "
                           "('preparing','ready','installing','unknown','recovery_required')").fetchone(),
            "component_switching")


def validate_snapshot(db, store, snapshot: Snapshot, *, indexed=False, all_rows=None) -> list[dict]:
    require(snapshot.session_id == store.session_id and snapshot.workspace == store.workspace,
            "snapshot_binding_mismatch")
    require(getmeta(db, "mode") == "active", "component_not_active")
    require(snapshot.generation == getmeta(db, "generation"), "stale_generation")
    require(snapshot.control_epoch == getmeta(db, "control_epoch"), "control_changed")
    require(snapshot.understanding_epoch == getmeta(db, "understanding_epoch"), "understanding_changed")
    # all_rows lets a caller that already read this transaction's sources reuse
    # them; the digest and pairing checks below still run on those rows.
    prefix = events.safe_boundary(db, snapshot.cut, indexed=indexed, all_rows=all_rows)
    require(digest(prefix) == snapshot.source_digest, "source_binding_changed")
    return prefix


def view_record(db, view_id: str) -> dict:
    row = db.execute("SELECT data FROM views WHERE id=?", (view_id,)).fetchone()
    require(row is not None, "view_unavailable")
    value = json.loads(row[0])
    require(value["digest"] == digest(value["body"]), "view_integrity_mismatch")
    return value
