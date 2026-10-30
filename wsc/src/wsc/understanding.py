"""Model-authored records with explicit revision and source provenance."""
from dataclasses import asdict
import json

from .contracts import Understanding, encode, identifier, require
from .events import rows
from .store import getmeta, setmeta
from .understanding_identity import write_identity


def all_records(db) -> list[dict]:
    return [json.loads(r[0]) for r in db.execute("SELECT data FROM understandings ORDER BY id,revision")]


def resolve(db, ref: str) -> dict:
    # Stored references are looked up as exact identities, never parsed as paths.
    row = db.execute("SELECT data FROM understandings WHERE ref=?", (ref,)).fetchone()
    require(row is not None, "understanding_reference_missing")
    return json.loads(row[0])


def write(db, value: Understanding, *, producer: str, allowed_sources=None) -> dict:
    identifier(producer)
    require(isinstance(value.text, str) and bool(value.text.strip()), "understanding_text_empty")
    identifier(value.kind)
    require(value.scope is None or isinstance(value.scope, dict), "invalid_understanding_scope")
    known = {r["id"] for r in rows(db)} if allowed_sources is None else set(allowed_sources)
    require(set(value.sources) <= known, "understanding_source_missing")
    key = write_identity(value)
    previous = db.execute("SELECT MAX(revision) FROM understandings WHERE id=?", (key,)).fetchone()[0]
    require((previous is None and value.expected_revision is None) or
            (previous is not None and value.expected_revision == previous), "understanding_revision_conflict")
    revision = (previous or 0) + 1
    record = {**asdict(value), "id": key, "revision": revision,
              "ref": f"{key}@{revision}", "producer": producer,
              "previous": f"{key}@{previous}" if previous else None}
    record.pop("expected_revision")
    db.execute("INSERT INTO understandings VALUES (?,?,?,?)", (key, revision, record["ref"], encode(record)))
    setmeta(db, "understanding_epoch", getmeta(db, "understanding_epoch") + 1)
    return record
