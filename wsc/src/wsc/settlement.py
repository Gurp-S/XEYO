"""Settle a proven host commit without re-admitting it as a new installation.

The host receipt binds the installation-time control epoch. Later control or
understanding updates remain in the source/record tail; they do not undo that
commit. Source identity and the local generation still fence local settlement.
"""
from dataclasses import asdict

from . import events
from .contracts import HostReceipt, HostRejection, digest, encode, require
from .store import getmeta


def check_committed_binding(db, store, data, *, indexed=False):
    binding = data["binding"]
    require(binding["session_id"] == store.session_id and binding["workspace"] == store.workspace,
            "snapshot_binding_mismatch")
    require(getmeta(db, "mode") == "active", "component_not_active")
    require(binding["generation"] == getmeta(db, "generation"), "stale_generation")
    prefix = (events.rows(db, binding["cut"]) if data["detach"] else
              events.safe_boundary(db, binding["cut"],indexed=indexed))
    require(digest(prefix) == binding["source_digest"], "source_binding_changed")


def record_lost_reply(db, operation_id):
    # A different recovery caller may already have committed a terminal result.
    db.execute("UPDATE operations SET state='unknown' WHERE id=? AND state='installing'",
               (operation_id,))


def record_unsettled_receipt(db, operation_id, receipt):
    value = encode(asdict(receipt)) if isinstance(receipt, (HostReceipt, HostRejection)) else None
    db.execute("UPDATE operations SET state='recovery_required',receipt=? WHERE id=? "
               "AND state IN ('installing','unknown','recovery_required')", (value, operation_id))
