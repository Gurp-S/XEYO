"""Incremental event integrity: append-only hash chain plus a verified cursor.

The chain links every event row's recorded digest to its predecessor, so a
rewritten, reordered, or truncated history is detectable.  Two cursors keep the
cost proportional to *new* rows rather than to the whole history:
``chained_through`` (how far the chain has been extended) and
``verified_through`` (how far the text has been re-hashed and checked).

Nothing here is enabled implicitly: callers opt in with ``policy='chain_v1'``
and the tables are created on first use.  Existing tables are never altered.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .contracts import require

POLICY = "chain_v1"
GENESIS = "0" * 64

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_event_chain_v1(
        seq INTEGER PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE,
        digest TEXT NOT NULL,
        link TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_integrity_state_v1(
        name TEXT PRIMARY KEY,
        chained_through INTEGER NOT NULL,
        verified_through INTEGER NOT NULL,
        head TEXT NOT NULL
    )""",
)


def installed(db) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wsc_event_chain_v1'"
                      ).fetchone() is not None


def install(db) -> None:
    # Individual statements, not executescript: executescript commits the open
    # transaction, which would break the single-transaction ingest guarantee.
    for statement in _SCHEMA:
        db.execute(statement)


def _ensure(db) -> None:
    if not installed(db):
        install(db)


def link(prev: str, seq: int, event_id: str, digest: str) -> str:
    return sha256(f"{prev}\n{seq}\n{event_id}\n{digest}".encode("utf-8")).hexdigest()


def _state(db) -> tuple[int, int, str]:
    row = db.execute("SELECT chained_through, verified_through, head FROM wsc_integrity_state_v1 "
                     "WHERE name='events'").fetchone()
    return (0, 0, GENESIS) if row is None else (int(row[0]), int(row[1]), row[2])


def _save(db, chained: int, verified: int, head: str) -> None:
    db.execute("INSERT INTO wsc_integrity_state_v1(name, chained_through, verified_through, head) "
               "VALUES ('events',?,?,?) ON CONFLICT(name) DO UPDATE SET "
               "chained_through=excluded.chained_through, "
               "verified_through=excluded.verified_through, head=excluded.head",
               (chained, verified, head))


def advance(db) -> dict:
    """Link event rows newer than the chained cursor. Idempotent; O(new rows)."""
    _ensure(db)
    chained, verified, head = _state(db)
    scanned = hashed = 0
    for seq, event_id, digest in db.execute(
            "SELECT seq, id, digest FROM events WHERE seq>? ORDER BY seq", (chained,)).fetchall():
        head = link(head, seq, event_id, digest)
        db.execute("INSERT OR REPLACE INTO wsc_event_chain_v1(seq, event_id, digest, link) "
                   "VALUES (?,?,?,?)", (seq, event_id, digest, head))
        chained = seq
        scanned += 1
        hashed += len(digest)
    if scanned:
        _save(db, chained, verified, head)
    return {"scanned": scanned, "hashed": hashed, "through": chained}


def verify(db, *, full: bool = False) -> dict:
    """Re-hash chained events beyond the verified cursor and check the links.

    Raises ``source_integrity_mismatch`` when stored text no longer matches its
    recorded digest, and ``integrity_chain_broken`` when a chain row is missing,
    reordered, or relinked.
    """
    _ensure(db)
    chained, verified, head = _state(db)
    if full:
        verified, prev = 0, GENESIS
    elif verified:
        row = db.execute("SELECT link FROM wsc_event_chain_v1 WHERE seq=?", (verified,)).fetchone()
        require(row is not None, "integrity_chain_broken")
        prev = row[0]
    else:
        prev = GENESIS
    scanned = hashed = 0
    expected = verified + 1
    last = verified
    for seq, event_id, digest, data, recorded in db.execute(
            "SELECT c.seq, c.event_id, c.digest, e.data, c.link FROM wsc_event_chain_v1 c "
            "JOIN events e ON e.seq=c.seq WHERE c.seq>? ORDER BY c.seq", (verified,)).fetchall():
        require(seq == expected, "integrity_chain_broken")
        require(sha256(data.encode("utf-8")).hexdigest() == digest, "source_integrity_mismatch")
        require(link(prev, seq, event_id, digest) == recorded, "integrity_chain_broken")
        prev, last, expected = recorded, seq, seq + 1
        scanned += 1
        hashed += len(data)
    if scanned:
        _save(db, chained, last, head)
    return {"scanned": scanned, "hashed": hashed, "through": last, "ok": True}


_RECEIPT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_receipt_chain_v1(
        rowid_ INTEGER PRIMARY KEY,
        receipt_id TEXT NOT NULL UNIQUE,
        source_ids TEXT NOT NULL,
        link TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_receipt_state_v1(
        name TEXT PRIMARY KEY,
        chained_through INTEGER NOT NULL,
        head TEXT NOT NULL
    )""",
)


def receipts_installed(db) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wsc_receipt_chain_v1'"
                      ).fetchone() is not None


def install_receipts(db) -> None:
    for statement in _RECEIPT_SCHEMA:
        db.execute(statement)


def _receipt_state(db) -> tuple[int, str]:
    row = db.execute("SELECT chained_through, head FROM wsc_receipt_state_v1 WHERE name='receipts'").fetchone()
    return (0, GENESIS) if row is None else (int(row[0]), row[1])


def _save_receipts(db, chained: int, head: str) -> None:
    db.execute("INSERT INTO wsc_receipt_state_v1(name, chained_through, head) VALUES ('receipts',?,?) "
               "ON CONFLICT(name) DO UPDATE SET chained_through=excluded.chained_through, head=excluded.head",
               (chained, head))


def advance_receipts(db) -> dict:
    """Link presentation receipts newer than the cursor. Idempotent; O(new receipts)."""
    if not receipts_installed(db):
        install_receipts(db)
    chained, head = _receipt_state(db)
    scanned = 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations WHERE rowid>? ORDER BY rowid", (chained,)).fetchall():
        head = link(head, rowid, receipt_id, sha256(data.encode("utf-8")).hexdigest())
        source_ids = " ".join(json.loads(data)["source_ids"])
        db.execute("INSERT OR REPLACE INTO wsc_receipt_chain_v1(rowid_, receipt_id, source_ids, link) "
                   "VALUES (?,?,?,?)", (rowid, receipt_id, source_ids, head))
        chained = rowid
        scanned += 1
    if scanned:
        _save_receipts(db, chained, head)
    return {"scanned": scanned, "through": chained, "head": head}


def verify_receipts(db) -> dict:
    """Recompute the receipt chain from scratch and compare it with the recorded head."""
    if not receipts_installed(db):
        return {"ok": True, "count": 0, "head": GENESIS}
    _, recorded = _receipt_state(db)
    head, count = GENESIS, 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations ORDER BY rowid").fetchall():
        head = link(head, rowid, receipt_id, sha256(data.encode("utf-8")).hexdigest())
        count += 1
    return {"ok": head == recorded, "count": count, "head": head}

def delivered(db) -> set[str]:
    """All presented source ids, backed by the receipt chain head."""
    report = verify_receipts(db)
    require(report["ok"], "presentation_receipt_integrity")
    return {source_id for row in db.execute("SELECT source_ids FROM wsc_receipt_chain_v1")
            for source_id in row[0].split()}
