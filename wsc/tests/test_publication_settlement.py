"""Observed host commits survive later input, lost replies and racing recovery."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc import WSC, Store, Selection, Understanding, WSCError, HostRejection
from wsc.adapters.callback import CallbackHost
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import encode
from test_contracts import DurableTestHost, message


class PublicationSettlementTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-settlement-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = self.reopen()
        self.adapter = CodexCheckpointAdapter()
        self.items = [message("user", "original request"), message("assistant", "observed diagnosis")]
        self.ids = self.core.ingest(self.adapter.import_items(self.items, thread_id="source"))
        self.host = DurableTestHost(self.root / "host.db", self.core, self.items)
        self.op = self.stage()

    def reopen(self):
        return WSC(Store(self.root / "wsc.db", session_id="session", workspace=str(self.root)),
                   access=lambda *args: True)

    def stage(self):
        view = self.core.prepare(self.core.capture(), Selection(), producer="offline_test")
        return self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)

    def append_control(self):
        item = message("user", "new constraint after installation")
        self.core.ingest(self.adapter.import_items([item], thread_id="new-control"))
        with closing(sqlite3.connect(self.host.path)) as db, db:
            state = self.host.state()
            state["items"].append(item)
            db.execute("UPDATE state SET data=? WHERE id=1", (encode(state),))
        return item

    def assert_settled_once(self, core):
        status = core.status()
        self.assertEqual("confirmed", status["operations"][0]["state"])
        self.assertEqual(1, status["generation"])
        self.assertEqual(2, status["cursor"])
        self.assertEqual(1, self.host.state()["effects"])

    def test_lost_reply_then_new_control_reconciles_after_reopen(self):
        self.host.lose_reply = True
        with self.assertRaises(TimeoutError):
            self.core.install(self.op, self.host)
        tail = self.append_control()
        reopened = self.reopen()
        reopened.reconcile(self.op, self.host)
        self.assert_settled_once(reopened)
        self.assertEqual(tail, self.host.state()["items"][-1])
        self.assertEqual(3, reopened.status()["source_count"])
        self.assertTrue(self.stage())

    def test_later_understanding_does_not_erase_committed_installation(self):
        def commit(package):
            receipt = self.host.install(package)
            self.core.remember(Understanding("new interpretation", "hypothesis", (self.ids[1],)),
                               producer="later_model_output")
            return receipt
        self.core.install(self.op, CallbackHost(commit=commit, lookup=self.host.lookup))
        self.assert_settled_once(self.core)
        self.assertEqual("new interpretation", self.core.capture().understandings[-1]["text"])
        self.assertTrue(self.stage())

    def test_late_timeout_cannot_downgrade_concurrently_confirmed_operation(self):
        def commit(package):
            self.host.install(package)
            self.reopen().reconcile(self.op, self.host)
            raise TimeoutError("original_reply_lost_after_other_recovery")
        with self.assertRaises(TimeoutError):
            self.core.install(self.op, CallbackHost(commit=commit, lookup=self.host.lookup))
        self.assert_settled_once(self.core)
        self.core.reconcile(self.op, self.host)
        self.assertTrue(self.stage())

    def test_late_conflicting_reply_cannot_downgrade_confirmed_operation(self):
        def commit(package):
            receipt = self.host.install(package)
            self.reopen().reconcile(self.op, self.host)
            return replace(receipt, generation=999)
        with self.assertRaisesRegex(WSCError, "host_receipt_conflict"):
            self.core.install(self.op, CallbackHost(commit=commit, lookup=self.host.lookup))
        self.assert_settled_once(self.core)
        self.assertEqual(1, self.core.reconcile(self.op, self.host)["generation"])

    def test_late_interrupt_keeps_unknown_then_reconciles_real_commit(self):
        def commit(package):
            self.host.install(package)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.core.install(self.op, CallbackHost(commit=commit, lookup=self.host.lookup))
        self.assertEqual("unknown", self.core.status()["operations"][0]["state"])
        self.append_control()
        reopened = self.reopen()
        reopened.reconcile(self.op, self.host)
        self.assert_settled_once(reopened)

    def test_late_timeout_cannot_erase_durable_rejection(self):
        receipt_path = self.root / "host-rejection.json"
        def lookup(key):
            return HostRejection(**json.loads(receipt_path.read_text(encoding="utf-8")))
        def commit(package):
            from dataclasses import asdict
            receipt = HostRejection(self.op, package["package_digest"], "session",
                                    str(self.root.resolve()), "capacity_rejected", "offline_test_host")
            receipt_path.write_text(encode(asdict(receipt)), encoding="utf-8")
            self.reopen().reconcile(self.op, CallbackHost(commit=lambda p: None, lookup=lookup))
            raise TimeoutError("rejection_reply_lost")
        host = CallbackHost(commit=commit, lookup=lookup)
        with self.assertRaises(TimeoutError):
            self.core.install(self.op, host)
        self.assertEqual("rejected", self.core.status()["operations"][0]["state"])
        self.assertEqual("capacity_rejected", self.core.reconcile(self.op, host)["reason"])
        self.assertEqual(0, self.host.state()["effects"])
        self.assertTrue(self.stage())


if __name__ == "__main__":
    unittest.main()
