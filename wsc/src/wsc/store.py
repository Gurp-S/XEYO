"""One explicitly bound session per SQLite file; all mutations are serialized."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Iterator

from .contracts import encode, identifier, require


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 data TEXT NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL, call_id TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS call_kind ON events(call_id,kind) WHERE call_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS presentations (
 id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS understandings (
 id TEXT NOT NULL, revision INTEGER NOT NULL, ref TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
 PRIMARY KEY(id, revision));
CREATE TABLE IF NOT EXISTS views (
 id TEXT PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
 data TEXT NOT NULL, receipt TEXT);
CREATE TABLE IF NOT EXISTS usage (
 id TEXT PRIMARY KEY, phase TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
"""


def getmeta(db: sqlite3.Connection, key: str):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def getmetas(db: sqlite3.Connection, keys) -> dict:
    """Read several meta values in one statement instead of one query per key.

    `status` used to issue five `getmeta` calls; the values live in one indexed
    table, so one `IN` statement returns the same mapping without five round
    trips through the connection.
    """
    keys = tuple(keys)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    rows = db.execute(f"SELECT key,value FROM meta WHERE key IN ({marks})", keys)
    found = {key: json.loads(value) for key, value in rows}
    return {key: found.get(key) for key in keys}


def setmeta(db: sqlite3.Connection, key: str, value) -> None:
    db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, encode(value)))


class Store:
    def __init__(self, path: str | Path, *, session_id: str, workspace: str):
        self.path = Path(path).resolve()
        self.session_id = identifier(session_id)
        self.workspace = str(Path(workspace).resolve())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            binding = {"schema": 1, "session_id": self.session_id, "workspace": self.workspace}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require(not tables or "meta" in tables, "store_format_unknown")
            existing = getmeta(db, "binding") if "meta" in tables else None
            require(not tables or existing == binding, "store_binding_mismatch")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            if existing is None:
                setmeta(db, "binding", binding)
                for key, value in {"generation": 0, "control_epoch": 0,
                                   "understanding_epoch": 0, "cursor": 0,
                                   "head": None, "mode": "active"}.items():
                    setmeta(db, key, value)
            else:
                require(existing == binding, "store_binding_mismatch")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            # Read-side knobs only; neither changes what is durable on disk.
            db.execute("PRAGMA mmap_size=268435456")
            db.execute("PRAGMA cache_size=-65536")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
