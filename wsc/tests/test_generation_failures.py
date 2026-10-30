"""Actual command/CLI failures keep neutral output and known accounting."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.cli import main
from wsc.generation import JsonCommandGenerator


class GenerationFailureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-generation-failure-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: True)
        self.core.ingest(CodexCheckpointAdapter().import_items([{"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "task"}]}], thread_id="s"))

    def command(self, value):
        program = self.root / "fixture.py"
        program.write_text("import json\nprint(json.dumps(" + repr(value) + "))\n", encoding="utf-8")
        return JsonCommandGenerator([sys.executable, str(program)])

    def test_invalid_selection_keeps_known_usage_in_failed_attempt(self):
        generator = self.command({"selection": {"source_ids": 8},
                                  "usage": {"input_uncached": 19, "output": 7}})
        with self.assertRaisesRegex(WSCError, "source_reference_list_invalid"):
            self.core.generate(self.core.capture(), generator, producer="offline")
        report = self.core.status()["usage"]
        self.assertEqual("failed", report["attempts"][0]["status"])
        self.assertEqual(19, report["totals"]["input_uncached"]["known_sum"])
        self.assertEqual(7, report["totals"]["output"]["known_sum"])
        self.assertEqual(1, report["totals"]["input_cached"]["unknown_attempts"])
        with self.core.store.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM views").fetchone()[0])
        with self.assertRaisesRegex(WSCError, "generation_budget_exhausted"):
            self.core.generate(self.core.capture(), generator, producer="offline")

    def test_cli_actual_command_timeout_is_neutral_and_usage_stays_unknown(self):
        argv = [sys.executable, "-c", "import time; time.sleep(5) # private-command-detail"]
        path = self.root / "argv.json"
        path.write_text(json.dumps(argv), encoding="utf-8")
        output, error = io.StringIO(), io.StringIO()
        with patch("wsc.generation.JsonCommandGenerator", side_effect=lambda value:
                   JsonCommandGenerator(value, timeout=0.05)), contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(error):
            status = main(["--db", str(self.core.store.path), "--session", "s", "--workspace",
                           str(self.root), "generate", "--producer", "offline", "--command-json", str(path)])
        self.assertEqual(2, status)
        self.assertEqual("", output.getvalue())
        self.assertEqual({"error": "generation_command_timeout"}, json.loads(error.getvalue()))
        report = self.core.status()["usage"]
        self.assertEqual("failed", report["attempts"][0]["status"])
        self.assertEqual(1, report["totals"]["output"]["unknown_attempts"])

    def test_valid_command_and_partial_usage_still_work(self):
        view = self.core.generate(self.core.capture(), self.command({"selection": {},
            "usage": {"input_uncached": 0, "output": 2}}), producer="offline")
        self.assertTrue(view)
        report = self.core.status()["usage"]
        self.assertEqual("completed", report["attempts"][0]["status"])
        self.assertEqual(0, report["totals"]["input_uncached"]["unknown_attempts"])
        self.assertEqual(1, report["totals"]["input_cached"]["unknown_attempts"])


if __name__ == "__main__":
    unittest.main()
