"""Full-audit checkpoints: reuse only for the exact receipt range audited."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc import WSC, Store, Selection, WSCError, events, integrity, publication
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.audit_cache import audit_receipts_cached, latest_checkpoint, validate_anchor
from wsc.contracts import Event, encode


def message(role, text):
    return {"type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}


def unguard(db):
    """Simulate an offline writer: committed receipts are append-only by trigger."""
    for trigger in ("wsc_receipts_append_only_update", "wsc_receipts_append_only_delete",
                    "wsc_receipt_chain_append_only_update", "wsc_receipt_chain_append_only_delete"):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")


class AuditCacheChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wsc-audit-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = self.reopen()
        self.ids = self.core.ingest([Event("e1", "observation", {}, text="hello")])
        with self.core.store.transaction() as db:
            integrity.install_receipts(db)
            events.presented(db, "r1", tuple(self.ids), "model")

    def reopen(self, session="s"):
        return WSC(Store(self.root / "state.db", session_id=session, workspace=str(self.root)),
                   access=lambda *a: True)

    def audit(self, session_id="s", **kwargs):
        with self.core.store.transaction() as db:
            return audit_receipts_cached(db, session_id=session_id, **kwargs)

    def checkpoint(self, session="s"):
        with self.core.store.transaction() as db:
            return latest_checkpoint(db, session)

    def present(self, receipt_id):
        with self.core.store.transaction() as db:
            events.presented(db, receipt_id, tuple(self.ids), "model")

    def test_first_release_runs_a_full_audit_and_records_a_checkpoint(self):
        report = self.audit()
        self.assertTrue(report["ok"], report)
        self.assertFalse(report["reused"])
        self.assertEqual("full", report["scope"])
        self.assertEqual((1, 1, 1), (report["count"], report["scanned"], report["checkpoint_count"]))
        self.assertGreater(report["hashed"], 0)
        saved = self.checkpoint()
        self.assertEqual((1, 1, "ok"), (saved["count"], saved["integrity_version"], saved["status"]))
        self.assertEqual(report["head"], saved["head"])

    def test_unchanged_head_reuses_the_checkpoint_without_rehashing(self):
        self.audit()
        with mock.patch("wsc.integrity.verify_receipts", side_effect=AssertionError("rescan")):
            report = self.audit()
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["reused"])
        self.assertEqual("cached", report["scope"])
        self.assertEqual((0, 0), (report["scanned"], report["hashed"]))

    def test_new_receipt_invalidates_the_checkpoint(self):
        self.audit()
        self.present("r2")
        report = self.audit()
        self.assertFalse(report["reused"])
        self.assertEqual((2, 2), (report["scanned"], report["count"]))
        self.assertEqual(2, self.checkpoint()["count"])

    def test_protocol_version_change_invalidates_the_checkpoint(self):
        self.audit()
        with mock.patch("wsc.integrity.RECEIPT_INTEGRITY_VERSION", 2):
            report = self.audit()
        self.assertFalse(report["reused"])
        self.assertEqual(1, report["scanned"])
        self.assertEqual(2, self.checkpoint()["integrity_version"])

    def test_failed_audit_never_becomes_a_checkpoint(self):
        with self.core.store.transaction() as db:
            original = db.execute("SELECT data FROM presentations WHERE id='r1'").fetchone()[0]
            unguard(db)
            db.execute("UPDATE presentations SET data=? WHERE id='r1'",
                       (encode({"source_ids": [], "receiver": "model"}),))
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertEqual("receipt_audit_failed", report["reason"])
        self.assertIsNone(self.checkpoint())
        with self.core.store.transaction() as db:
            unguard(db)
            db.execute("UPDATE presentations SET data=? WHERE id='r1'", (original,))
        report = self.audit()
        self.assertTrue(report["ok"], report)
        self.assertFalse(report["reused"])
        self.assertEqual(1, report["scanned"])

    def test_corrupted_checkpoint_is_not_reused(self):
        self.audit()
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_integrity_audits_v1 SET audited_receipt_count=99")
        report = self.audit()
        self.assertFalse(report["reused"])
        self.assertTrue(report["ok"], report)
        self.assertEqual(1, report["scanned"])
        self.assertEqual(1, self.checkpoint()["count"])

    def test_checkpoints_are_scoped_to_one_session(self):
        self.audit()
        other = self.audit(session_id="other")
        self.assertFalse(other["reused"])
        self.assertTrue(self.audit(session_id="other")["reused"])
        self.assertEqual(1, self.checkpoint("s")["count"])
        self.assertEqual(1, self.checkpoint("other")["count"])

    def test_anchor_mismatch_fails_closed(self):
        report = self.audit()
        self.assertTrue(self.audit(anchor=report["head"])["reused"])
        with self.assertRaisesRegex(WSCError, "integrity_anchor_mismatch"):
            self.audit(anchor=integrity.GENESIS)
        with self.assertRaisesRegex(WSCError, "integrity_anchor_invalid"):
            validate_anchor("not-a-digest")

    def test_committed_receipts_are_append_only(self):
        with self.core.store.transaction() as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt_immutable"):
                db.execute("UPDATE presentations SET data='{}' WHERE id='r1'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt_immutable"):
                db.execute("DELETE FROM presentations WHERE id='r1'")
        self.assertEqual(1, self.audit()["count"])

    def test_inconsistent_chain_falls_back_to_a_full_audit(self):
        with self.core.store.transaction() as db:
            unguard(db)
            db.execute("DELETE FROM wsc_receipt_chain_v1")
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertEqual("receipt_state_inconsistent", report["reason"])
        self.assertIsNone(self.checkpoint())

    def test_legacy_audit_without_a_checkpoint_is_repeated_once(self):
        with self.core.store.transaction() as db:
            integrity.audit_receipts(db)
        self.assertIsNone(self.checkpoint())
        report = self.audit()
        self.assertFalse(report["reused"])
        self.assertEqual(1, report["scanned"])
        self.assertEqual(1, self.checkpoint()["count"])

    def test_stage_reports_full_then_cached_assurance(self):
        core = WSC(Store(self.root / "publish.db", session_id="s", workspace=str(self.root)),
                   access=lambda *a: True)
        adapter = CodexCheckpointAdapter()
        items = [message("user", "request"), message("assistant", "answer")]
        ids = core.ingest(adapter.import_items(items, thread_id="thread"))
        with core.store.transaction() as db:
            integrity.install_receipts(db)
            events.presented(db, "r1", tuple(ids), "model")

        def stage():
            view = core.prepare(core.capture(), Selection(), producer="offline_test")
            return core.stage(view, directory=self.root / "exports", adapter=adapter)

        def audit_of(operation_id):
            with core.store.transaction() as db:
                return publication.operation(db, operation_id)["receipt_audit"]

        first = stage()
        self.assertEqual(("full", False), (audit_of(first)["scope"], audit_of(first)["reused"]))
        core.discard(first)
        view = core.prepare(core.capture(), Selection(), producer="offline_test")
        with mock.patch("wsc.integrity.audit_receipts", side_effect=AssertionError("full rescan")):
            second = core.stage(view, directory=self.root / "exports", adapter=adapter)
        self.assertEqual(("cached", True), (audit_of(second)["scope"], audit_of(second)["reused"]))
        core.discard(second)
        with core.store.transaction() as db:
            events.presented(db, "r2", tuple(ids), "model")
        third = stage()
        self.assertEqual(("full", False), (audit_of(third)["scope"], audit_of(third)["reused"]))
        self.assertEqual(2, audit_of(third)["count"])


if __name__ == "__main__":
    unittest.main()
