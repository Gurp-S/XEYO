"""Transactional mailbox storage; delivery is reserved before transcript writes."""
import time
import uuid
from engine.agent_identity import AgentBusy


class AgentMessageStore:
    def import_legacy(self, session, agent, generation, queue, pending):
        with self.connection(write=True) as db:
            row = db.execute("SELECT attempt FROM agents WHERE session=? AND agent=?", (session, agent)).fetchone()
            if not row:
                raise AgentBusy("unknown_recipient")
            self._delivery_owner(db, session, agent, row["attempt"])
            imported = db.execute("SELECT 1 FROM legacy_imports WHERE session=? AND agent=? AND generation=?",
                                  (session, agent, generation)).fetchone()
            items = list(queue)
            if not imported:
                unmatched = [item["text"] for item in queue]
                for index, text in enumerate(pending):
                    if text in unmatched:
                        unmatched.remove(text)
                    else:
                        items.append({"text": text, "message_id": f"legacy-meta-{generation}-{index}"})
            for item in items:
                if not item["text"].strip() or len(item["text"]) > 8000:
                    raise ValueError("invalid_message_text")
                self._insert_message(db, session, agent, "parent", item["text"], item["message_id"], "message", row["attempt"])
            db.execute("INSERT OR IGNORE INTO legacy_imports VALUES (?,?,?)", (session, agent, generation))

    @staticmethod
    def _insert_message(db, session, recipient, sender, text, mid, kind, attempt):
        prior = db.execute("SELECT * FROM mailbox WHERE session=? AND sender=? AND message_id=?",
                           (session, sender, mid)).fetchone()
        if prior:
            if prior["recipient"] != recipient or prior["text"] != text or prior["kind"] != kind:
                raise ValueError("message_id_conflict")
            return dict(prior)
        if kind != "completion" and db.execute("SELECT count(*) FROM mailbox WHERE session=? AND recipient=? AND state IN ('queued','delivering')",
                      (session, recipient)).fetchone()[0] >= 256:
            raise AgentBusy("mailbox_capacity_exhausted")
        db.execute("""INSERT INTO mailbox(session,recipient,sender,message_id,text,kind,target_attempt,created)
            VALUES (?,?,?,?,?,?,?,?)""", (session, recipient, sender, mid, text, kind, attempt, time.time()))
        return dict(db.execute("SELECT * FROM mailbox WHERE seq=last_insert_rowid()").fetchone())

    def send(self, session, recipient, sender, text, *, message_id="", expected_attempt="", sender_attempt="", kind="message"):
        if not text.strip() or len(text) > 8000:
            raise ValueError("invalid_message_text")
        with self.connection(write=True) as db:
            if db.execute("SELECT 1 FROM closed_sessions WHERE session=?", (session,)).fetchone():
                raise AgentBusy("session_deleted")
            if sender != "parent":
                owner = db.execute("SELECT attempt,state FROM agents WHERE session=? AND agent=?",
                                   (session, sender)).fetchone()
                if not owner:
                    raise ValueError("unknown_sender")
                if sender_attempt and (owner["attempt"] != sender_attempt or owner["state"] not in ("running", "cancelling")):
                    raise AgentBusy("stale_sender_attempt")
            target = None if recipient == "parent" else db.execute(
                "SELECT attempt FROM agents WHERE session=? AND agent=?", (session, recipient)).fetchone()
            if recipient != "parent" and target is None:
                raise ValueError("unknown_recipient")
            attempt = target["attempt"] if target else ""
            if expected_attempt and expected_attempt != attempt:
                raise AgentBusy("stale_agent_attempt")
            return self._insert_message(db, session, recipient, sender, text,
                                        message_id or uuid.uuid4().hex, kind, attempt)

    def pending(self, session, recipient, *, limit=32):
        with self.connection() as db:
            return [dict(r) for r in db.execute("""SELECT * FROM mailbox WHERE session=?
                AND recipient=? AND state IN ('queued','delivering') ORDER BY seq LIMIT ?""", (session, recipient, limit))]

    @staticmethod
    def _delivery_owner(db, session, recipient, attempt):
        if db.execute("SELECT 1 FROM closed_sessions WHERE session=?", (session,)).fetchone():
            raise AgentBusy("session_deleted")
        if recipient != "parent":
            row = db.execute("SELECT attempt,state FROM agents WHERE session=? AND agent=?",
                             (session, recipient)).fetchone()
            if not row or row["attempt"] != attempt or row["state"] not in ("running", "cancelling"):
                raise AgentBusy("stale_agent_attempt")

    def claim_messages(self, session, recipient, *, attempt="", limit=32):
        # The caller holds a delivery OS lease. After a crash, the next owner
        # replays delivering rows with their stable transcript IDs.
        with self.connection(write=True) as db:
            self._delivery_owner(db, session, recipient, attempt)
            rows = [dict(r) for r in db.execute("""SELECT * FROM mailbox WHERE session=?
                AND recipient=? AND state IN ('queued','delivering') ORDER BY seq LIMIT ?""",
                (session, recipient, limit))]
            for row in rows:
                db.execute("UPDATE mailbox SET state='delivering' WHERE seq=?", (row["seq"],))
            return rows

    def acknowledge(self, session, recipient, sequences, *, attempt=""):
        with self.connection(write=True) as db:
            self._delivery_owner(db, session, recipient, attempt)
            for seq in sequences:
                db.execute("UPDATE mailbox SET state='delivered' WHERE session=? AND recipient=? AND seq=? AND state='delivering'",
                           (session, recipient, seq))

    def remove_message(self, session, recipient, *, message_id="", text="", sender="parent"):
        with self.connection(write=True) as db:
            field, value = ("message_id", message_id) if message_id else ("text", text)
            row = db.execute(f"SELECT seq FROM mailbox WHERE session=? AND recipient=? AND sender=? AND state='queued' AND {field}=? ORDER BY seq LIMIT 1",
                             (session, recipient, sender, value)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE mailbox SET state='cancelled' WHERE seq=?", (row["seq"],))
            return True
