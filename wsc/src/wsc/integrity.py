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

# Additive tables: the source index answers "was this id presented?" in O(1),
# and the verify cursor keeps a receipt check proportional to new receipts.
_RECEIPT_AUX_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_receipt_sources_v1(
        source_id TEXT PRIMARY KEY,
        receipt_id TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_receipt_verified_v1(
        name TEXT PRIMARY KEY,
        verified_rowid INTEGER NOT NULL,
        verified_link TEXT NOT NULL
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


def _ensure_receipt_aux(db) -> None:
    """Create the source index and verify cursor; backfill the index once."""
    created = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                         "AND name='wsc_receipt_sources_v1'").fetchone() is None
    for statement in _RECEIPT_AUX_SCHEMA:
        db.execute(statement)
    if created:
        for receipt_id, source_ids in db.execute(
                "SELECT receipt_id, source_ids FROM wsc_receipt_chain_v1").fetchall():
            for source_id in source_ids.split():
                db.execute("INSERT OR IGNORE INTO wsc_receipt_sources_v1 VALUES (?,?)",
                           (source_id, receipt_id))


def advance_receipts(db) -> dict:
    """Link presentation receipts newer than the cursor. Idempotent; O(new receipts)."""
    if not receipts_installed(db):
        install_receipts(db)
    _ensure_receipt_aux(db)
    chained, head = _receipt_state(db)
    scanned = 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations WHERE rowid>? ORDER BY rowid", (chained,)).fetchall():
        head = link(head, rowid, receipt_id, sha256(data.encode("utf-8")).hexdigest())
        source_ids = " ".join(json.loads(data)["source_ids"])
        db.execute("INSERT OR REPLACE INTO wsc_receipt_chain_v1(rowid_, receipt_id, source_ids, link) "
                   "VALUES (?,?,?,?)", (rowid, receipt_id, source_ids, head))
        for source_id in source_ids.split():
            db.execute("INSERT OR IGNORE INTO wsc_receipt_sources_v1 VALUES (?,?)",
                       (source_id, receipt_id))
        chained = rowid
        scanned += 1
    if scanned:
        _save_receipts(db, chained, head)
    return {"scanned": scanned, "through": chained, "head": head}


def _receipt_verified(db) -> tuple[int, str]:
    row = db.execute("SELECT verified_rowid, verified_link FROM wsc_receipt_verified_v1 "
                     "WHERE name='receipts'").fetchone()
    return (0, GENESIS) if row is None else (int(row[0]), row[1])


def _save_receipt_verified(db, rowid: int, head: str) -> None:
    db.execute("INSERT INTO wsc_receipt_verified_v1(name, verified_rowid, verified_link) "
               "VALUES ('receipts',?,?) ON CONFLICT(name) DO UPDATE SET "
               "verified_rowid=excluded.verified_rowid, verified_link=excluded.verified_link",
               (rowid, head))


def verify_receipts(db, *, full: bool = False) -> dict:
    """Check receipts against the chain, re-hashing only receipts past the cursor.

    New receipts are re-hashed and compared with their chain links, and the chain
    head must still equal the recorded head. A chain that ends before the
    presentations table does is reported as ``ok=False`` (truncation). Rewriting a
    receipt that was already verified adds no new row, so ``full=True`` recomputes
    the entire chain for explicit audits instead of the ingest path.
    """
    if not receipts_installed(db):
        return {"ok": True, "count": 0, "scanned": 0, "head": GENESIS}
    _ensure_receipt_aux(db)
    _, recorded = _receipt_state(db)
    chain_max = db.execute("SELECT COALESCE(MAX(rowid_),0) FROM wsc_receipt_chain_v1").fetchone()[0]
    rows_max = db.execute("SELECT COALESCE(MAX(rowid),0) FROM presentations").fetchone()[0]
    if chain_max != rows_max:
        return {"ok": False, "count": 0, "scanned": 0, "head": recorded}
    if full:
        start, prev = 0, GENESIS
    else:
        start, prev = _receipt_verified(db)
        if start:
            row = db.execute("SELECT link FROM wsc_receipt_chain_v1 WHERE rowid_=?", (start,)).fetchone()
            if row is None or row[0] != prev:
                return {"ok": False, "count": 0, "scanned": 0, "head": recorded}
    head, last, scanned = prev, start, 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations WHERE rowid>? ORDER BY rowid", (start,)).fetchall():
        expected = link(head, rowid, receipt_id, sha256(data.encode("utf-8")).hexdigest())
        row = db.execute("SELECT link FROM wsc_receipt_chain_v1 WHERE rowid_=?", (rowid,)).fetchone()
        if row is None or row[0] != expected:
            return {"ok": False, "count": 0, "scanned": scanned, "head": head}
        head, last = expected, rowid
        scanned += 1
    if scanned:
        _save_receipt_verified(db, last, head)
    return {"ok": head == recorded, "count": last if full else scanned,
            "scanned": scanned, "head": head}


def delivered(db) -> set[str]:
    """All presented source ids, after an incremental receipt check."""
    if not receipts_installed(db):
        return set()
    require(verify_receipts(db)["ok"], "presentation_receipt_integrity")
    return {row[0] for row in db.execute("SELECT source_id FROM wsc_receipt_sources_v1")}


def is_delivered(db, source_id: str, *, verified: bool = False) -> bool:
    """Whether one source was presented; ``verified`` skips the receipt check."""
    if not receipts_installed(db):
        return False
    if not verified:
        require(verify_receipts(db)["ok"], "presentation_receipt_integrity")
    return db.execute("SELECT 1 FROM wsc_receipt_sources_v1 WHERE source_id=?",
                      (source_id,)).fetchone() is not None
