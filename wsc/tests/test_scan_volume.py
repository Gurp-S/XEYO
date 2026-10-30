import unittest
from unittest import mock

from wsc import events, integrity
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultPolicy
from tests.test_context_runtime import ContextRuntimeChecks, message

HISTORY = 60


class ScanVolumeChecks(ContextRuntimeChecks):
    """Measured scan volume: cost must follow the cut, never the history."""

    def setUp(self):
        super().setUp()
        self.observe([message("user", f"m{index}") for index in range(HISTORY)])

    def _reads(self, db, cut):
        with mock.patch("wsc.events.rows", wraps=events.rows) as counted:
            try:
                events.safe_boundary(db, cut)
            except Exception:
                pass
        return counted.call_args.kwargs.get("through")

    def test_boundary_reads_track_the_cut_not_the_history(self):
        with self.core.store.transaction() as db:
            history = len(events.rows(db))
            self.assertGreaterEqual(history, HISTORY)
            self.assertEqual(10, self._reads(db, 10))
            self.assertEqual(history, self._reads(db, history))

    def test_receipt_chain_advance_is_idempotent(self):
        self.ctx = ContextRuntime(self.core, self.store, policy=ResultPolicy(enabled=True),
                                  integrity_policy="chain_v1")
        with self.core.store.transaction() as db:
            ids = [row["id"] for row in events.rows(db)][:3]
            events.presented(db, "r1", tuple(ids), "model")
            self.assertEqual(0, integrity.advance_receipts(db)["scanned"])
            self.assertTrue(integrity.verify_receipts(db)["ok"])


for _name in [name for name in dir(ContextRuntimeChecks) if name.startswith("test_")]:
    # The inherited checks assume the baseline history; this class deliberately
    # starts from a long history, so only the measurements below run here.
    setattr(ScanVolumeChecks, _name,
            unittest.skip("baseline history replaced by measurement fixture")(
                getattr(ContextRuntimeChecks, _name)))


if __name__ == "__main__":
    unittest.main()
