"""Durable runs and mailboxes. Transactions provide admission and message identity.

This store does not plan work. Mail delivery is at least once across crashes;
stable message IDs allow transcript insertion to be idempotent. Acknowledgement
means recorded in the receiving transcript, not that its task has succeeded.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from engine.agent_identity import AgentBusy, AgentIdentity, AgentLease

ACTIVE = ("running", "cancelling")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _path(value):
    return os.path.normcase(os.path.realpath(value)).replace("\\", "/").rstrip("/")


def overlaps(left, right):
    return any(a == b or a.startswith(b + "/") or b.startswith(a + "/")
               for a in left for b in right)


from engine.agent_message_store import AgentMessageStore


class AgentRunStore(AgentMessageStore):
    def __init__(self, directory: Path | None = None):
        if directory is None:
            from session.persistence import default_sessions_dir
            directory = default_sessions_dir() / "_agent_runtime"
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "runs.sqlite3"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    session TEXT NOT NULL, agent TEXT NOT NULL, attempt TEXT NOT NULL,
                    state TEXT NOT NULL, spec TEXT NOT NULL, root TEXT NOT NULL,
                    scope TEXT NOT NULL, result TEXT, artifact TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(session, agent));
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt TEXT PRIMARY KEY, session TEXT, agent TEXT, state TEXT,
                    spec TEXT, result TEXT, created REAL, updated REAL);
                CREATE TABLE IF NOT EXISTS mailbox (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
                    recipient TEXT NOT NULL, sender TEXT NOT NULL, message_id TEXT NOT NULL,
                    text TEXT NOT NULL, kind TEXT NOT NULL, target_attempt TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL,
                    UNIQUE(session, sender, message_id));
                CREATE INDEX IF NOT EXISTS mailbox_recipient
                    ON mailbox(session, recipient, state, seq);
                CREATE TABLE IF NOT EXISTS closed_sessions (session TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS legacy_imports (
                    session TEXT, agent TEXT, generation TEXT,
                    PRIMARY KEY(session,agent,generation));
                CREATE INDEX IF NOT EXISTS agents_state ON agents(state);
            """)

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=5000")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def lease(self, session, agent):
        return AgentLease(self.directory / "leases", session, agent)

    @staticmethod
    def decode(row):
        if row is None:
            return None
        value = dict(row)
        for key in ("spec", "scope", "result", "artifact"):
            if key in value:
                value[key] = json.loads(value[key]) if value[key] else None
        return value

    def get(self, session, agent):
        with self.connection() as db:
            return self.decode(db.execute("SELECT * FROM agents WHERE session=? AND agent=?",
                                          (session, agent)).fetchone())

    def list(self, session):
        with self.connection() as db:
            return [self.decode(r) for r in db.execute(
                "SELECT * FROM agents WHERE session=? ORDER BY created", (session,))]

    def recover(self):
        """Only an obtainable OS lease proves that an active owner is gone."""
        with self.connection() as db:
            active = [dict(r) for r in db.execute(
                "SELECT session,agent,attempt FROM agents WHERE state IN ('running','cancelling')")]
        for row in active:
            lease = self.lease(row["session"], row["agent"])
            try:
                lease.acquire()
            except AgentBusy:
                continue
            try:
                current = self.get(row["session"], row["agent"])
                if not current or current["attempt"] != row["attempt"] or current["state"] not in ACTIVE:
                    continue
                identity = AgentIdentity(row["session"], row["agent"], row["attempt"])
                final = {"detail": "execution owner exited"}
                try:
                    from engine.agent_artifact_state import recover_owner
                    recover_owner(self, identity, current)
                except Exception as exc:
                    final["artifact_recovery_error"] = str(exc)
                self.finish(identity, "interrupted", final)
            finally:
                lease.release()

    def start(self, session, agent, spec, *, session_limit=8, total_limit=32, expected_attempt=None):
        if not session or not agent or agent == "parent":
            raise ValueError("invalid_agent_identity")
        self.recover()
        lease = self.lease(session, agent).acquire()
        try:
            root = _path(spec["cwd"])
            scopes = ([_path(Path(root) / p) for p in spec.get("scope", [])]
                      if spec.get("isolation") == "shared" else [])
            attempt = uuid.uuid4().hex
            now = time.time()
            with self.connection(write=True) as db:
                if db.execute("SELECT 1 FROM closed_sessions WHERE session=?", (session,)).fetchone():
                    raise AgentBusy("session_deleted")
                rows = db.execute("SELECT session,scope FROM agents WHERE state IN ('running','cancelling')").fetchall()
                if len(rows) >= total_limit or sum(r["session"] == session for r in rows) >= session_limit:
                    raise AgentBusy("agent_capacity_exhausted")
                if scopes and any(overlaps(scopes, json.loads(r["scope"])) for r in rows):
                    raise AgentBusy("write_scope_busy")
                old = db.execute("SELECT attempt,spec,artifact FROM agents WHERE session=? AND agent=?", (session, agent)).fetchone()
                if expected_attempt is not None and expected_attempt != (old["attempt"] if old else ""):
                    raise AgentBusy("stale_agent_attempt")
                if old:
                    original = json.loads(old["spec"])
                    for field in ("cwd", "scope", "isolation", "required_tools", "agent_type"):
                        if spec.get(field) != original.get(field):
                            raise AgentBusy("agent_spec_changed: " + field)
                from engine.agent_artifact_state import reconcile
                artifact = _json(reconcile(json.loads(old["artifact"]), resuming=True)) if old and old["artifact"] else None
                db.execute("""INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(session,agent) DO UPDATE SET attempt=excluded.attempt,
                    state=excluded.state,spec=excluded.spec,root=excluded.root,scope=excluded.scope,
                    result=NULL,artifact=excluded.artifact,created=excluded.created,updated=excluded.updated""",
                    (session, agent, attempt, "running", _json(spec), root, _json(scopes), None, artifact, now, now))
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?)",
                           (attempt, session, agent, "running", _json(spec), None, now, now))
                # Explicit continuation of this identity carries undelivered messages.
                db.execute("UPDATE mailbox SET target_attempt=? WHERE session=? AND recipient=? AND state IN ('queued','delivering')",
                           (attempt, session, agent))
            return AgentIdentity(session, agent, attempt, now), lease
        except BaseException:
            lease.release()
            raise

    def finish(self, identity, state, result):
        if state not in TERMINAL:
            raise ValueError("invalid_terminal_state")
        with self.connection(write=True) as db:
            cursor = db.execute("""UPDATE agents SET state=?,result=?,updated=?
                WHERE session=? AND agent=? AND attempt=? AND state IN ('running','cancelling')""",
                (state, _json(result), time.time(), identity.session_id, identity.agent_id, identity.attempt_id))
            if not cursor.rowcount:
                return False
            db.execute("UPDATE attempts SET state=?,result=?,updated=? WHERE attempt=?",
                       (state, _json(result), time.time(), identity.attempt_id))
            self._insert_message(db, identity.session_id, "parent", identity.agent_id,
                _json({"agent_id": identity.agent_id, "attempt_id": identity.attempt_id, "state": state}),
                "completion-" + identity.attempt_id, "completion", "")
            return True

    def drop_session(self, session):
        self.recover()
        with self.connection(write=True) as db:
            if db.execute("SELECT 1 FROM agents WHERE session=? AND state IN ('running','cancelling')", (session,)).fetchone():
                raise AgentBusy("agents_stopping")
            from engine.agent_delivery_guard import deletion_guard
            recipients = [r[0] for r in db.execute("SELECT agent FROM agents WHERE session=?", (session,))]
            with deletion_guard(self, session, recipients):
                db.execute("INSERT OR IGNORE INTO closed_sessions VALUES (?)", (session,))
                for table in ("agents", "attempts", "mailbox", "legacy_imports"):
                    db.execute(f"DELETE FROM {table} WHERE session=?", (session,))

    def artifact(self, identity, artifact):
        with self.connection(write=True) as db:
            changed = db.execute("UPDATE agents SET artifact=?,updated=? WHERE session=? AND agent=? AND attempt=?",
                (_json(artifact), time.time(), identity.session_id, identity.agent_id, identity.attempt_id)).rowcount
            if not changed:
                raise AgentBusy("stale_agent_attempt")

