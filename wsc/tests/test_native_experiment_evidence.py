"""Accounting failures must stop a paid experiment, never silently become zero."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_evidence import FIELDS, contains_sequence, import_evidence, records, usage


class NativeEvidenceTests(unittest.TestCase):
    def receipt(self, response="r1"):
        value = dict.fromkeys(FIELDS, 0)
        value.update(input_tokens=10, cached_input_tokens=4, output_tokens=2, total_tokens=12)
        return {"type": "token_usage_record", "payload": {
            "thread_id": "t1", "response_id": response, "usage": value}}

    def test_duplicate_receipts_count_once_and_compaction_is_charged(self):
        row = self.receipt()
        result = usage([row, copy.deepcopy(row), {"type": "compacted", "payload": {
            "compaction_response_id": "r1"}}], "t1")
        self.assertEqual(result["response_count"], 1)
        self.assertEqual(result["all_usage"]["total_tokens"], 12)
        self.assertEqual(result["compaction_usage"]["total_tokens"], 12)
        self.assertEqual(result["duplicate_receipt_ids"], ["r1"])
        self.assertIsNone(result["cash"])

    def test_conflicting_receipt_rejected(self):
        row, other = self.receipt(), self.receipt()
        other["payload"]["usage"]["output_tokens"] = 3
        with self.assertRaisesRegex(ValueError, "conflicting"):
            usage([row, other], "t1")

    def test_unknown_usage_does_not_become_zero(self):
        for key in FIELDS:
            with self.subTest(key=key):
                row = self.receipt()
                del row["payload"]["usage"][key]
                with self.assertRaisesRegex(ValueError, "unknown"):
                    usage([row], "t1")

    def test_unbound_compaction_rejected(self):
        with self.assertRaisesRegex(ValueError, "binding_unknown"):
            usage([self.receipt(), {"type": "compacted", "payload": {"compaction_response_id": "other"}}], "t1")

    def test_other_thread_receipt_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity_mismatch"):
            usage([self.receipt()], "other")

    def test_import_must_preserve_role_content_envelope_and_order(self):
        items = [{"role": "user", "id": "one"}, {"role": "assistant", "id": "two"}]
        self.assertTrue(contains_sequence([{}, *items, {}], items))
        self.assertFalse(contains_sequence(list(reversed(items)), items))
        changed = copy.deepcopy(items)
        changed[0]["id"] = "regenerated"
        self.assertFalse(contains_sequence(changed, items))

    def test_partial_last_receipt_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_bytes(b'{"type":"complete"}\n{"type":"token_usage_record"')
            self.assertEqual(records(path), [{"type": "complete"}])

    def test_observed_native_additions_keep_all_supplied_fields(self):
        supplied = [{"type": "reasoning", "encrypted_content": "opaque"},
                    {"type": "message", "role": "developer", "content": []}]
        observed = [dict(supplied[0], content=None), dict(supplied[1], id="new")]
        result = import_evidence(observed, supplied)
        self.assertTrue(result["matched"])
        self.assertFalse(result["exact_sequence"])
        self.assertEqual(len(result["native_added_fields"]), 2)
        observed[0]["content"] = ["unexpected"]
        self.assertFalse(import_evidence(observed, supplied)["matched"])

    def test_normalization_cannot_change_existing_identity_or_content(self):
        supplied = [{"type": "message", "role": "user", "id": "original", "content": []}]
        self.assertFalse(import_evidence([dict(supplied[0], id="new")], supplied)["matched"])
        self.assertFalse(import_evidence([dict(supplied[0], role="developer")], supplied)["matched"])


if __name__ == "__main__":
    unittest.main()
