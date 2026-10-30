"""Opaque native state is preserved as a bound protocol value, never decoded."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSCError
from wsc.adapters.native_carrier import NativeCarrierCheckpointAdapter
from wsc.contracts import digest
from test_contracts import message


class NativeCarrierTests(unittest.TestCase):
    def setUp(self):
        self.prefix = [message("user", "Original requirement"), message("assistant", "Historical diagnosis")]
        self.carrier = {"type": "compaction", "id": "native-id", "encrypted_content": "opaque-test-value"}
        payloads = self.prefix + [self.carrier, message("user", "New tail instruction")]
        self.sources = [{"id": str(i), "seq": i+1, "kind": "opaque" if i == 2 else "message",
                         "role": payload.get("role"), "payload": copy.deepcopy(payload)}
                        for i, payload in enumerate(payloads)]
        self.body = {"sources": [self.sources[0]], "understandings": [], "clues": [],
                     "excerpts": [{"key": "memory", "text": "Exact historical observation", "historical_locator": "old position"}],
                     "excerpt_locators": {"memory": {"file_path": "/cold/excerpt.txt", "observed_at": "historical-time"}}}
        self.adapter = NativeCarrierCheckpointAdapter(self.carrier, source_count=2,
            source_digest=digest(self.prefix), workspace=str(Path.cwd()))

    def render(self, sources=None, cut=3):
        return self.adapter.render(self.body, sources or self.sources, cut, {},
                                   source_index="/cold/sources.json", understanding_index="/cold/understandings.json")

    def test_one_unchanged_carrier_with_original_control_and_exact_tail(self):
        result = self.render()
        self.assertEqual(self.prefix[0], result[0])
        self.assertEqual(self.carrier, result[1])
        self.assertEqual(self.sources[-1]["payload"], result[-1])
        self.assertEqual(1, sum(r["type"] == "compaction" for r in result))
        self.assertEqual("assistant", result[2]["role"])
        self.assertIn("Exact historical observation", result[2]["content"][0]["text"])
        self.assertIn("historical-time", result[2]["content"][0]["text"])
        self.assertNotIn("opaque-test-value", result[2]["content"][0]["text"])

    def test_source_prefix_cannot_drift_under_a_retained_checkpoint(self):
        changed = copy.deepcopy(self.sources)
        changed[1]["payload"] = message("assistant", "Different source")
        with self.assertRaisesRegex(WSCError, "native_carrier_source_mismatch"):
            self.render(changed)

    def test_replaced_carrier_or_expanded_fold_boundary_is_rejected(self):
        changed = copy.deepcopy(self.sources)
        changed[2]["payload"]["encrypted_content"] = "other"
        with self.assertRaisesRegex(WSCError, "native_carrier_identity_mismatch"):
            self.render(changed)
        with self.assertRaisesRegex(WSCError, "native_carrier_boundary_mismatch"):
            self.render(cut=4)

    def test_original_carrier_mutation_does_not_change_registered_value(self):
        self.carrier["encrypted_content"] = "caller-mutated"
        self.assertEqual("opaque-test-value", self.render()[1]["encrypted_content"])

    def test_selected_historical_assistant_messages_cannot_duplicate_the_native_state(self):
        self.body["sources"].append(self.sources[1])
        with self.assertRaisesRegex(WSCError, "native_carrier_control_prefix_required"):
            self.render()


if __name__ == "__main__":
    unittest.main()
