"""Reject changed registered inputs before execution and keep CLI errors neutral."""
import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]
from wsc.cli import main
from wsc import Store
import run_admitted_pair
from run_native_pair import phase


class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-execution-boundary-")
        self.addCleanup(directory.cleanup)
        self.area = Path(directory.name)
        self.pin = self.area / "pinned-input"
        self.pin.write_bytes(b"changed")
        self.reg = {"pins": {str(self.pin): sha256(b"registered").hexdigest()},
                    "origin": str(self.area / "origin"), "initial_manifest": {}}

    def test_retained_entry_rejects_pin_drift_before_workspace_setup(self):
        (self.area / "registration.json").write_text(json.dumps(self.reg), encoding="utf-8")
        with patch.object(run_admitted_pair, "require_qualification"), patch.object(
                run_admitted_pair, "protect_origin", side_effect=RuntimeError("past_pin_gate")):
            with self.assertRaisesRegex(ValueError, "registered_input_changed"):
                run_admitted_pair.run(self.area)
        self.assertFalse((self.area / "started.json").exists())

    def test_each_phase_rechecks_pins_before_sending_a_model_request(self):
        opened = {"thread": {"id": "test", "path": str(self.area / "missing-rollout")}}
        with self.assertRaisesRegex(ValueError, "registered_input_changed"):
            phase(None, opened, self.reg, self.area, None, time.monotonic() + 1)
        self.assertFalse((self.area / "attempt-started.json").exists())

    def test_corrupt_database_uses_neutral_cli_error_exit(self):
        database = self.area / "corrupt.db"
        database.write_bytes(b"not a sqlite database")
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(["--db", str(database), "--session", "s", "--workspace", str(self.area), "status"])
        self.assertEqual(2, status)
        self.assertEqual("", output.getvalue())
        self.assertEqual({"error": "DatabaseError"}, json.loads(error.getvalue()))

    def test_sqlite_lock_error_does_not_leak_detail_or_traceback(self):
        error = io.StringIO()
        with patch("wsc.cli.Store", side_effect=sqlite3.OperationalError("private internal detail")), contextlib.redirect_stderr(error):
            status = main(["--db", str(self.area / "db"), "--session", "s", "--workspace", str(self.area), "status"])
        self.assertEqual(2, status)
        self.assertEqual({"error": "OperationalError"}, json.loads(error.getvalue()))

    def test_connection_initialization_error_still_closes_the_connection(self):
        store = Store.__new__(Store)
        store.path = self.area / "not-opened"
        with patch("wsc.store.sqlite3.connect") as connect:
            connection = connect.return_value
            connection.execute.side_effect = sqlite3.DatabaseError("initialization_failed")
            with self.assertRaisesRegex(sqlite3.DatabaseError, "initialization_failed"):
                with store.connect():
                    self.fail("Initialization unexpectedly succeeded")
            connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
