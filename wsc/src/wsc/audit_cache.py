"""Persistent full-audit checkpoints for the receipt chain.

Publication must be able to say "the whole receipt history was verified" without
re-hashing that history on every ``stage()``.  A checkpoint binds one successful
full audit to the exact range it covered: session, chain head, receipt count and
integrity protocol version.  A later release reuses the result only when every
one of those fields still matches; any mismatch - including an unknown or
unreadable checkpoint - falls back to a full audit.  Nothing is inferred from a
global boolean.

The checkpoint is a claim *about* an audit, never a substitute for one.  A hit
reports ``scope='cached'`` and ``reused=True`` so callers can tell it apart from
``scope='full'``.  What a hit proves is that the chain head, the receipt count
and the protocol version are unchanged; it does not re-hash receipt text.  An
in-place rewrite that keeps the head unchanged is therefore invisible to a hit.
The normal path cannot make such a write (the receipt table is append-only under
guards installed with the chain), and an explicit ``audit_receipts()`` still
detects it - that is the assurance boundary this module reports rather than
hides.

Existing databases keep working: the audit table is additive, and a database
that only carries the legacy ``full_verified_through`` column has no checkpoint,
so its first publication runs a full audit and writes one.
"""
from __future__ import annotations

from hashlib import sha256
import os

from . import integrity
from .contracts import require

SCOPE = "receipts"
STATUS_OK = "ok"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_integrity_audits_v1(
        audit_id INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        audited_chain_head TEXT NOT NULL,
        audited_receipt_count INTEGER NOT NULL,
        integrity_version INTEGER NOT NULL,
        full_audited_at TEXT NOT NULL,
        audit_status TEXT NOT NULL,
        integrity_root TEXT NOT NULL,
        audit_digest TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS wsc_integrity_audits_v1_lookup
        ON wsc_integrity_audits_v1(session_id, scope, audit_id)""",
)

_HEX = frozenset("0123456789abcdef")
ENV_ANCHOR = "WSC_INTEGRITY_ANCHOR"


def validate_anchor(anchor: str | None) -> str | None:
    """Reject a malformed anchor at configuration time, not at release time."""
    if anchor is None:
        return None
    require(isinstance(anchor, str) and len(anchor) == 64 and set(anchor) <= _HEX,
            "integrity_anchor_invalid")
    return anchor


def _anchor(anchor: str | None) -> str | None:
    if anchor is None:
        anchor = (os.environ.get(ENV_ANCHOR) or "").strip() or None
    return validate_anchor(anchor)


def _seal(session_id: str, head: str, count: int, version: int, at: str, status: str,
          root: str) -> str:
    return sha256(f"{session_id}\n{SCOPE}\n{head}\n{count}\n{version}\n{at}\n{status}\n{root}"
                  .encode("utf-8")).hexdigest()


def _ensure_schema(db) -> None:
    for statement in _SCHEMA:
        db.execute(statement)


def _latest(db, session_id: str):
    return db.execute(
        "SELECT audit_id, audited_chain_head, audited_receipt_count, integrity_version, "
        "full_audited_at, audit_status, integrity_root, audit_digest "
        "FROM wsc_integrity_audits_v1 WHERE session_id=? AND scope=? "
        "ORDER BY audit_id DESC LIMIT 1", (session_id, SCOPE)).fetchone()


def latest_checkpoint(db, session_id: str) -> dict | None:
    """The newest checkpoint for one session, for inspection and tests."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                  "AND name='wsc_integrity_audits_v1'").fetchone() is None:
        return None
    row = _latest(db, session_id)
    if row is None:
        return None
    try:
        return {"audit_id": int(row[0]), "head": row[1], "count": int(row[2]),
                "integrity_version": int(row[3]), "full_audited_at": row[4],
                "status": row[5], "root": row[6]}
    except (TypeError, ValueError):
        return {"audit_id": None, "head": None, "count": None, "integrity_version": None,
                "full_audited_at": None, "status": None, "root": None}


def _chain_state(db) -> tuple[str, int, bool]:
    """(head, receipt count, confirmed) from the persisted receipt state.

    The count is read from ``wsc_receipt_state_v1``, never from ``COUNT(*)``, so
    a cache hit costs O(1) in history size.  ``confirmed`` requires the state
    row, the chain's last row and the receipts' last row to agree on the same
    position and head; an unbackfilled count (``-1``) or any disagreement is not
    confirmed and forces one full audit, which repairs the state on success.
    """
    status = integrity.receipt_status(db)
    if status is None:
        empty_chain = db.execute("SELECT 1 FROM wsc_receipt_chain_v1 LIMIT 1").fetchone() is None
        empty_rows = db.execute("SELECT 1 FROM presentations LIMIT 1").fetchone() is None
        return integrity.GENESIS, 0, empty_chain and empty_rows
    count, chained, head = status
    chain_last = db.execute("SELECT rowid_, link FROM wsc_receipt_chain_v1 "
                            "ORDER BY rowid_ DESC LIMIT 1").fetchone()
    rows_last = db.execute("SELECT COALESCE(MAX(rowid),0) FROM presentations").fetchone()[0]
    last_rowid = 0 if chain_last is None else int(chain_last[0])
    last_link = integrity.GENESIS if chain_last is None else chain_last[1]
    confirmed = (count >= 0 and chained == last_rowid == int(rows_last) and head == last_link)
    return head, max(count, 0), confirmed


def _reusable(row, session_id: str, head: str, count: int, version: int) -> bool:
    """Every binding field must match and the checkpoint must still seal.

    Any unparseable field (wrong SQLite storage class, missing text, truncated
    seal) makes the checkpoint unusable rather than raising: the caller then
    runs a full audit.
    """
    try:
        if row is None or row[5] != STATUS_OK:
            return False
        stored_head, stored_count, stored_version = row[1], int(row[2]), int(row[3])
        at, status, root, seal = row[4], row[5], row[6], row[7]
        if not all(isinstance(value, str) and value for value in (stored_head, at, root, seal)):
            return False
        if stored_version != version or stored_head != head or stored_count != count or root != head:
            return False
        return _seal(session_id, head, count, version, at, status, root) == seal
    except (TypeError, ValueError):
        return False


def _result(*, ok: bool, reused: bool, scope: str, count: int, scanned: int, hashed: int,
            head: str, version: int, full_audited_at: str | None, checkpoint_count: int | None,
            reason: str | None) -> dict:
    return {"ok": ok, "reused": reused, "scope": scope, "count": count, "scanned": scanned,
            "hashed": hashed, "head": head, "integrity_version": version,
            "full_audited_at": full_audited_at, "checkpoint_count": checkpoint_count,
            "reason": reason}


def audit_receipts_cached(db, *, session_id: str, anchor: str | None = None) -> dict:
    """Reuse a matching full-audit checkpoint, otherwise audit the whole history.

    The checkpoint is written only after a successful audit and inside the
    caller's transaction, so a failed or rolled-back audit cannot leave a
    reusable claim behind.  ``anchor`` (or ``WSC_INTEGRITY_ANCHOR``) pins the
    expected chain head to a value held outside this database; a mismatch is a
    hard failure rather than a cache miss.
    """
    require(isinstance(session_id, str) and session_id, "audit_session_missing")
    version = integrity.RECEIPT_INTEGRITY_VERSION
    pinned = _anchor(anchor)
    if not integrity.receipts_installed(db):
        require(pinned is None or pinned == integrity.GENESIS, "integrity_anchor_mismatch")
        return _result(ok=True, reused=False, scope="none", count=0, scanned=0, hashed=0,
                       head=integrity.GENESIS, version=version, full_audited_at=None,
                       checkpoint_count=None, reason="no_receipts")
    head, count, confirmed = _chain_state(db)
    if pinned is not None:
        require(pinned == head, "integrity_anchor_mismatch")
    _ensure_schema(db)
    row = _latest(db, session_id)
    if confirmed and _reusable(row, session_id, head, count, version):
        return _result(ok=True, reused=True, scope="cached", count=count, scanned=0, hashed=0,
                       head=head, version=version, full_audited_at=row[4],
                       checkpoint_count=int(row[2]), reason=None)
    # An unconfirmed state (unknown count, chain/presentation disagreement) is
    # not reused and not assumed fatal: the full audit below is the only thing
    # allowed to decide whether the history is intact.
    report = integrity.verify_receipts(db, full=True)
    if not report["ok"]:
        return _result(ok=False, reused=False, scope="full", count=count,
                       scanned=report["scanned"], hashed=report["hashed"], head=head,
                       version=version, full_audited_at=report["last_full_audit_at"],
                       checkpoint_count=None,
                       reason="receipt_state_inconsistent" if not confirmed else "receipt_audit_failed")
    if confirmed:
        require(report["head"] == head and report["count"] == count, "receipt_audit_range_moved")
    else:
        head, count = report["head"], report["count"]
        integrity.record_receipt_count(db, count)
    at = report["last_full_audit_at"] or ""
    db.execute(
        "INSERT INTO wsc_integrity_audits_v1(session_id, scope, audited_chain_head, "
        "audited_receipt_count, integrity_version, full_audited_at, audit_status, "
        "integrity_root, audit_digest) VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, SCOPE, head, count, version, at, STATUS_OK, head,
         _seal(session_id, head, count, version, at, STATUS_OK, head)))
    return _result(ok=True, reused=False, scope="full", count=count, scanned=report["scanned"],
                   hashed=report["hashed"], head=head, version=version,
                   full_audited_at=at, checkpoint_count=count, reason=None)
