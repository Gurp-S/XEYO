import unittest
from unittest import mock

from wsc import events, integrity
from wsc.contracts import WSCError, encode
from wsc.store import getmeta
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultPolicy
from tests.test_context_runtime import ContextRuntimeChecks, message


class IntegrityWiringChecks(ContextRuntimeChecks):
    def test_default_runtime_leaves_no_chain(self):
        with self.core.store.transaction() as db:self.assertFalse(integrity.installed(db))

    def test_chain_policy_chains_inside_the_ingest_transaction(self):
        self.ctx = ContextRuntime(self.core, self.store, policy=ResultPolicy(enabled=True),
                                  integrity_policy="chain_v1")
        with self.core.store.transaction() as db:self.assertTrue(integrity.installed(db))
        self.observe([message("user", "chain me")])
        with self.core.store.transaction() as db:report = integrity.verify(db)
        self.assertTrue(report["ok"], report)
        with self.core.store.transaction() as db:self.assertEqual(len(events.rows(db)), report["through"])

    def test_receipt_chain_detects_tampering(self):
        self.ctx = ContextRuntime(self.core, self.store, policy=ResultPolicy(enabled=True),
                                  integrity_policy="chain_v1")
        with self.core.store.transaction() as db:
            ids = [row["id"] for row in events.rows(db)]
            events.presented(db, "r1", tuple(ids), "model")
            self.assertTrue(integrity.verify_receipts(db)["ok"])
            db.execute("UPDATE presentations SET data=? WHERE id='r1'",
                       (encode({"source_ids": [], "receiver": "model"}),))
            self.assertFalse(integrity.verify_receipts(db)["ok"])

    def test_tampered_receipts_fail_the_boundary_check(self):
        self.ctx = ContextRuntime(self.core, self.store, policy=ResultPolicy(enabled=True),
                                  integrity_policy="chain_v1")
        with self.core.store.transaction() as db:
            ids = [row["id"] for row in events.rows(db)]
            events.presented(db, "r1", tuple(ids), "model")
            cut = max(1, getmeta(db, "cursor") or 0)
            db.execute("UPDATE presentations SET data=? WHERE id='r1'",
                       (encode({"source_ids": [], "receiver": "model"}),))
            with self.assertRaisesRegex(WSCError, "presentation_receipt_integrity"):
                events.safe_boundary(db, cut)

    def test_safe_boundary_reads_only_the_prefix(self):
        with mock.patch("wsc.events.rows", wraps=events.rows) as counted:
            try:
                with self.core.store.transaction() as db:events.safe_boundary(db, 1)
            except Exception:
                pass
        self.assertEqual(1, counted.call_args.kwargs.get("through"))


if __name__ == "__main__":
    unittest.main()
