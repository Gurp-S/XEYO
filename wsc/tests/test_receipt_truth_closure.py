"""Receipt truth closure: authoritative receipts, derived chain, derived index.

Every test here tampers with one derived structure while leaving the
authoritative receipt untouched, and asserts a deterministic outcome.  No test
asks a model or a human whether the result "looks right".
"""
import json
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from wsc import Selection, audit_cache, events, integrity
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import Event, WSCError
from wsc.core import WSC
from wsc.store import Store

CHAIN_GUARDS = ("wsc_receipt_chain_append_only_update", "wsc_receipt_chain_append_only_delete")
RECEIPT_GUARDS = ("wsc_receipts_append_only_update", "wsc_receipts_append_only_delete")


def unguard(db):
    """Drop the append-only guards to simulate an offline writer."""
    for trigger in RECEIPT_GUARDS + CHAIN_GUARDS:
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")


class ClosureChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wsc-closure-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = self.open()
        self.ids = self.core.ingest([Event("e1", "observation", {}, text="hello"),
                                     Event("e2", "observation", {}, text="world")])
        with self.core.store.transaction() as db:
            integrity.install_receipts(db)
            events.presented(db, "r1", tuple(self.ids), "model")

    def open(self, session="s"):
        return WSC(Store(self.root / "state.db", session_id=session, workspace=str(self.root)),
                   access=lambda *a: True)

    def audit(self, session_id="s"):
        with self.core.store.transaction() as db:
            return audit_cache.audit_receipts_cached(db, session_id=session_id)

    def chain(self, db):
        return db.execute("SELECT rowid_, receipt_id, source_ids, link FROM wsc_receipt_chain_v1 "
                          "ORDER BY rowid_").fetchall()

    def tamper_chain(self, column, value):
        with self.core.store.transaction() as db:
            unguard(db)
            db.execute(f"UPDATE wsc_receipt_chain_v1 SET {column}=? WHERE rowid_=1", (value,))

    # T1/T2/T3: a single derived chain column, rewritten while the receipt stays.
    def test_T1_chain_receipt_id_tamper_fails_full_audit(self):
        self.tamper_chain("receipt_id", "forged")
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertEqual(0, report["scanned"])

    def test_T2_chain_source_ids_tamper_fails_full_audit(self):
        self.tamper_chain("source_ids", "e1")
        self.assertFalse(self.audit()["ok"])

    def test_T3_chain_link_tamper_fails_full_audit(self):
        self.tamper_chain("link", "0" * 64)
        self.assertFalse(self.audit()["ok"])

    # T4: the derived index can lie about a source, and a rebuild repairs it.
    def test_T4_source_index_tamper_is_detected_and_rebuilt(self):
        with self.core.store.transaction() as db:
            db.execute("DELETE FROM wsc_receipt_sources_v1")
            db.execute("INSERT INTO wsc_receipt_sources_v1 VALUES ('ghost','r1')")
            self.assertFalse(integrity.is_delivered(db, "ghost", verified=True))
            self.assertFalse(integrity.is_delivered(db, "e1", verified=True))
            report = integrity.rebuild_receipt_index(db)
            self.assertEqual(2, report["rebuilt"])
            self.assertTrue(integrity.is_delivered(db, "e1", verified=True))
            self.assertFalse(integrity.is_delivered(db, "ghost", verified=True))
            self.assertEqual({"e1", "e2"}, integrity.delivered(db))

    # T5: rewriting the authoritative receipt itself.
    def test_T5_receipt_rewrite_fails_full_audit(self):
        with self.core.store.transaction() as db:
            unguard(db)
            db.execute("UPDATE presentations SET data=? WHERE id='r1'",
                       (json.dumps({"source_ids": [], "receiver": "model"}),))
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertEqual("receipt_audit_failed", report["reason"])

    # T6: the normal path cannot rewrite or delete committed chain rows.
    def test_T6_chain_rows_are_immutable_on_the_normal_path(self):
        with self.core.store.transaction() as db:
            with self.assertRaises(sqlite3.IntegrityError) as update:
                db.execute("UPDATE wsc_receipt_chain_v1 SET link='x' WHERE rowid_=1")
            self.assertIn("receipt_chain_immutable", str(update.exception))
            with self.assertRaises(sqlite3.IntegrityError) as delete:
                db.execute("DELETE FROM wsc_receipt_chain_v1 WHERE rowid_=1")
            self.assertIn("receipt_chain_immutable", str(delete.exception))

    # T7: re-linking the same receipts is idempotent, not a rewrite.
    def test_T7_repeated_advance_is_idempotent(self):
        with self.core.store.transaction() as db:
            before = self.chain(db)
            self.assertEqual(0, integrity.advance_receipts(db)["scanned"])
            unguard(db)
            db.execute("DELETE FROM wsc_receipt_state_v1")
            db.execute("INSERT INTO wsc_receipt_state_v1(name, chained_through, head, receipt_count) "
                       "VALUES ('receipts',0,?,0)", (integrity.GENESIS,))
            report = integrity.advance_receipts(db)
            self.assertEqual(1, report["scanned"])
            self.assertEqual(before, self.chain(db))

    # T8: same position, different content is a conflict, never a replacement.
    def test_T8_same_id_with_different_content_is_rejected(self):
        with self.core.store.transaction() as db:
            unguard(db)
            db.execute("UPDATE wsc_receipt_chain_v1 SET receipt_id='forged' WHERE rowid_=1")
            db.execute("INSERT INTO wsc_receipt_state_v1(name, chained_through, head, receipt_count) "
                       "VALUES ('receipts',0,?,0) ON CONFLICT(name) DO UPDATE SET "
                       "chained_through=0, head=?, receipt_count=0", (integrity.GENESIS, integrity.GENESIS))
            with self.assertRaises(WSCError) as raised:
                integrity.advance_receipts(db)
            self.assertEqual("receipt_chain_conflict", str(raised.exception))

    # T9/T10: an unreadable checkpoint is never reused and never raises.
    def test_T9_T10_corrupt_checkpoints_fall_back_to_a_full_audit(self):
        self.audit()
        corruptions = (
            "UPDATE wsc_integrity_audits_v1 SET audited_receipt_count='not-a-number'",
            "UPDATE wsc_integrity_audits_v1 SET integrity_version='v1'",
            "UPDATE wsc_integrity_audits_v1 SET audit_digest=''",
            "UPDATE wsc_integrity_audits_v1 SET audited_chain_head='deadbeef'",
            "UPDATE wsc_integrity_audits_v1 SET audit_status='unknown'",
            "UPDATE wsc_integrity_audits_v1 SET full_audited_at=7",
        )
        for statement in corruptions:
            with self.subTest(statement=statement):
                with self.core.store.transaction() as db:
                    db.execute(statement)
                report = self.audit()
                self.assertTrue(report["ok"])
                self.assertFalse(report["reused"])
                self.assertEqual("full", report["scope"])

    def test_T9_deleted_checkpoint_is_a_cache_miss(self):
        self.audit()
        with self.core.store.transaction() as db:
            db.execute("DELETE FROM wsc_integrity_audits_v1")
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertFalse(report["reused"])
        self.assertEqual(1, report["scanned"])

    def test_T9_duplicate_conflicting_checkpoints_are_not_reused(self):
        self.audit()
        with self.core.store.transaction() as db:
            db.execute("INSERT INTO wsc_integrity_audits_v1(session_id, scope, audited_chain_head, "
                       "audited_receipt_count, integrity_version, full_audited_at, audit_status, "
                       "integrity_root, audit_digest) VALUES ('s','receipts','bad',99,1,'now','ok',"
                       "'bad','bad')")
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertFalse(report["reused"])

    # T11: a checkpoint survives a process restart.
    def test_T11_checkpoint_is_reused_after_restart(self):
        self.audit()
        reopened = self.open()
        with reopened.store.transaction() as db:
            report = audit_cache.audit_receipts_cached(db, session_id="s")
        self.assertTrue(report["ok"])
        self.assertTrue(report["reused"])
        self.assertEqual(0, report["scanned"])

    # T12: a new receipt invalidates the checkpoint.
    def test_T12_new_receipt_invalidates_the_checkpoint(self):
        self.audit()
        with self.core.store.transaction() as db:
            events.presented(db, "r2", (self.ids[0],), "model")
            integrity.advance_receipts(db)
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertFalse(report["reused"])
        self.assertEqual(2, report["count"])
        self.assertEqual(2, report["scanned"])
        self.assertGreater(report["hashed"], 0)

    # T13: sessions never share a checkpoint.
    def test_T13_sessions_do_not_share_checkpoints(self):
        self.audit()
        with self.core.store.transaction() as db:
            report = audit_cache.audit_receipts_cached(db, session_id="other")
        self.assertTrue(report["ok"])
        self.assertFalse(report["reused"])

    # T14: the audit runs inside the same write transaction as the publish.
    def test_T14_stage_audits_inside_the_write_transaction(self):
        core = self.open()
        adapter = CodexCheckpointAdapter()
        seen = {}
        original = integrity.verify_receipts

        def spy(db, *, full=False):
            seen["in_transaction"] = db.in_transaction
            return original(db, full=full)

        view = core.prepare(core.capture(), Selection(), producer="offline_test")
        with mock.patch.object(integrity, "verify_receipts", spy):
            core.stage(view, directory=self.root / "exports", adapter=adapter)
        self.assertTrue(seen["in_transaction"])

    # T15: the anchor pins the head and a stale anchor blocks release.
    def test_T15_anchor_semantics(self):
        with self.core.store.transaction() as db:
            first = audit_cache.audit_receipts_cached(db, session_id="s")
        with self.core.store.transaction() as db:
            cached = audit_cache.audit_receipts_cached(db, session_id="s", anchor=first["head"])
        self.assertTrue(cached["reused"])
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError) as raised:
                audit_cache.audit_receipts_cached(db, session_id="s", anchor="0" * 64)
        self.assertEqual("integrity_anchor_mismatch", str(raised.exception))
        with self.core.store.transaction() as db:
            events.presented(db, "r2", (self.ids[0],), "model")
            integrity.advance_receipts(db)
            second = audit_cache.audit_receipts_cached(db, session_id="s")
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError):
                audit_cache.audit_receipts_cached(db, session_id="s", anchor=first["head"])
            ok = audit_cache.audit_receipts_cached(db, session_id="s", anchor=second["head"])
        self.assertTrue(ok["ok"])

    # T16: a hit on a large history issues no COUNT and no receipt scan.
    def test_T16_cached_hit_does_no_count_and_no_hash(self):
        for index in range(120):
            with self.core.store.transaction() as db:
                events.presented(db, f"bulk{index}", (self.ids[0],), "model")
                integrity.advance_receipts(db)
        self.audit()
        statements = []
        with self.core.store.transaction() as db:
            db.set_trace_callback(statements.append)
            report = audit_cache.audit_receipts_cached(db, session_id="s")
            db.set_trace_callback(None)
        self.assertTrue(report["reused"])
        self.assertEqual(0, report["scanned"])
        self.assertEqual(0, report["hashed"])
        joined = "\n".join(statements).lower()
        self.assertNotIn("count(", joined)
        self.assertNotIn("select rowid, id, data from presentations", joined)

    def test_legacy_state_without_a_count_is_backfilled_once(self):
        self.audit()
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_state_v1 SET receipt_count=-1")
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertFalse(report["reused"])
        with self.core.store.transaction() as db:
            self.assertEqual(1, integrity.receipt_status(db)[0])


if __name__ == "__main__":
    unittest.main()
