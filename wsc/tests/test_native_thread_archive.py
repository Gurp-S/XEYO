"""Missing/partial/invalid logs stay unknown while other thread evidence survives."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_thread_archive import archive_threads
from native_evidence import FIELDS


class NativeThreadArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wsc-thread-archive-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def opened(self, name):
        return {"thread": {"id": name, "path": str(self.root / (name + ".jsonl"))}}

    def test_missing_rollout_is_an_explicit_unknown_not_an_absent_thread(self):
        result = archive_threads(self.root, {"missing": self.opened("missing")})
        self.assertEqual("rollout_missing", result["missing"]["accounting_error"])
        self.assertIsNone(result["missing"]["known_response_count"])
        self.assertNotIn("receipts", result["missing"])

    def test_partial_rollout_retains_known_receipts_and_exact_raw_bytes(self):
        receipt = {"type": "token_usage_record", "payload": {"thread_id": "partial", "response_id": "r1",
                    "usage": {**dict.fromkeys(FIELDS, 0), "input_tokens": 10, "total_tokens": 10}}}
        raw = json.dumps(receipt).encode() + b'\n{"type":'
        (self.root / "partial.jsonl").write_bytes(raw)
        result = archive_threads(self.root, {"partial": self.opened("partial")})["partial"]
        self.assertEqual("rollout_incomplete", result["accounting_error"])
        self.assertEqual(1, result["receipts"]["response_count"])
        self.assertEqual(raw, (self.root / "native-rollout-archive/partial.jsonl").read_bytes())

    def test_invalid_thread_does_not_prevent_another_thread_from_being_archived(self):
        (self.root / "bad.jsonl").write_bytes(b'not-json\n')
        (self.root / "warmup.jsonl").write_bytes(b'{"type":"session_meta","payload":{}}\n')
        result = archive_threads(self.root, {"bad": self.opened("bad"), "warmup": self.opened("warmup")})
        self.assertIn("accounting_error", result["bad"])
        self.assertIsNotNone(result["bad"]["sha256"])
        self.assertEqual(0, result["warmup"]["receipts"]["response_count"])
        self.assertNotIn("accounting_error", result["warmup"])

    def test_archive_hash_failure_is_local_to_that_thread(self):
        (self.root / "bad.jsonl").write_bytes(b'not-json\n')
        (self.root / "warmup.jsonl").write_bytes(b'{"type":"session_meta","payload":{}}\n')
        with patch("native_thread_archive.file_hash", side_effect=PermissionError("unreadable")):
            result = archive_threads(self.root, {"bad": self.opened("bad"), "warmup": self.opened("warmup")})
        self.assertIsNone(result["bad"]["sha256"])
        self.assertEqual("PermissionError", result["bad"]["archive_read_error"])
        self.assertEqual(0, result["warmup"]["receipts"]["response_count"])


if __name__ == "__main__":
    unittest.main()
