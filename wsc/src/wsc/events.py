"""Immutable event ingestion and protocol boundaries; no semantic inference."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json

from .contracts import Event, digest, encode, identifier, require
from .control_sources import is_control_source
from .store import getmeta, setmeta
from . import integrity


def rows(db, through: int | None = None) -> list[dict]:
    query = "SELECT * FROM events"
    args = ()
    if through is not None:
        query += " WHERE seq<=?"
        args = (through,)
    result = []
    for row in db.execute(query + " ORDER BY seq", args):
        # The stored text is exactly encode(payload) written at ingest, so the
        # recorded digest can be checked without re-serializing the payload.
        raw = row["data"]
        require(sha256(raw.encode("utf-8")).hexdigest() == row["digest"], "source_integrity_mismatch")
        result.append({"seq": row["seq"], **json.loads(raw)})
    return result


def ingest(db, events: list[Event]) -> list[str]:
    require(getmeta(db, "mode") != "detached", "component_detached")
    ids = []
    for event in events:
        identifier(event.id)
        require(event.kind in {"message", "call", "result", "opaque", "observation", "control"},
                "unsupported_event_kind")
        require(isinstance(event.payload, dict), "invalid_event_payload")
        require(event.role is None or event.role in {"system", "developer", "user", "assistant"},
                "invalid_event_role")
        require(type(event.control) is bool, "invalid_control_flag")
        require(event.observed_at is None or isinstance(event.observed_at, str), "invalid_observation_time")
        require(event.text is None or isinstance(event.text, str), "invalid_public_text")
        require(event.kind != "opaque" or event.text is None, "opaque_text_unavailable")
        data = asdict(event)
        old = db.execute("SELECT digest FROM events WHERE id=?", (event.id,)).fetchone()
        if old:
            require(old[0] == digest(data), "source_identity_conflict")
            ids.append(event.id)
            continue
        if event.kind in {"call", "result"}:
            identifier(event.call_id)
        if event.kind == "call":
            require(not db.execute("SELECT 1 FROM events WHERE kind='call' AND call_id=?",
                                   (event.call_id,)).fetchone(), "duplicate_call_identity")
        if event.kind == "result":
            require(bool(db.execute("SELECT 1 FROM events WHERE kind='call' AND call_id=?",
                                    (event.call_id,)).fetchone()), "unpaired_result")
            require(not db.execute("SELECT 1 FROM events WHERE kind='result' AND call_id=?",
                                   (event.call_id,)).fetchone(), "duplicate_result")
        else:
            require(event.kind == "call" or event.call_id is None, "unexpected_call_identity")
        db.execute("INSERT INTO events(id,data,digest,kind,call_id) VALUES (?,?,?,?,?)",
                   (event.id, encode(data), digest(data), event.kind, event.call_id))
        if is_control_source(data):
            setmeta(db, "control_epoch", getmeta(db, "control_epoch") + 1)
        ids.append(event.id)
    if integrity.installed(db):
        integrity.advance(db)
    return ids


def presented(db, request_id: str, source_ids: tuple[str, ...], receiver: str) -> None:
    identifier(request_id)
    identifier(receiver)
    require(all(db.execute("SELECT 1 FROM events WHERE id=?", (key,)).fetchone()
                for key in source_ids), "presentation_source_missing")
    data = {"source_ids": sorted(set(source_ids)), "receiver": receiver}
    old = db.execute("SELECT data FROM presentations WHERE id=?", (request_id,)).fetchone()
    if old:
        require(old[0] == encode(data), "presentation_identity_conflict")
    else:
        db.execute("INSERT INTO presentations VALUES (?,?)", (request_id, encode(data)))
    if integrity.receipts_installed(db):
        integrity.advance_receipts(db)


def safe_boundary(db, cut: int, *, indexed=False, all_rows=None) -> list[dict]:
    if indexed:
        from .scoped_queries import safe_boundary as scoped_boundary
        if all_rows is None:
            return scoped_boundary(db, cut, read_prefix=rows)
        return scoped_boundary(db, cut, read_prefix=lambda database, bound: all_rows[:bound])
    require(type(cut) is int and cut > 0 and cut >= getmeta(db, "cursor"), "invalid_fold_boundary")
    if all_rows is None:
        all_rows = rows(db, through=cut)
    require(cut <= len(all_rows), "source_boundary_missing")
    prefix = all_rows[:cut]
    pending = set()
    delivered = set()
    if integrity.receipts_installed(db):
        delivered = integrity.delivered(db)
    else:
        for receipt in db.execute("SELECT data FROM presentations"):
            delivered.update(json.loads(receipt[0])["source_ids"])
    for row in prefix:
        if row["kind"] == "call":
            pending.add(row["call_id"])
        elif row["kind"] == "result":
            pending.remove(row["call_id"])
            require(row["id"] in delivered, "result_presentation_unknown")
    require(not pending, "pending_tool_results")
    return prefix
