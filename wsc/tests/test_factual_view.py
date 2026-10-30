"""A shorter presentation preserves controls, tail, observations and provenance."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.factual_codex import FactualCodexCheckpointAdapter
from test_contracts import message


class FactualViewTests(unittest.TestCase):
    def setUp(self):
        control = {"id": "user", "seq": 1, "kind": "message", "payload": message("user", "Original constraint")}
        tail = {"id": "tail", "seq": 3, "kind": "message", "payload": message("assistant", "Unfolded tail")}
        self.source = [control, {"id": "call", "seq": 2, "kind": "observation",
                               "text": "Historical result", "observed_at": "yesterday",
                               "payload": message("assistant", "Historical result")}, tail]
        self.locators = {key: {"file_path": f"/archive/{key}.json", "readable_path": f"/archive/{key}.txt",
                              "sha256": "hash", "readable_sha256": "hash", "observed_at": "yesterday"}
                         for key in ("user", "call", "tail")}
        self.body = {"sources": [control, self.source[1]], "understandings": [{
            "ref": "diagnosis@1", "kind": "diagnosis", "text": "Existing interpretation",
            "scope": {"revision": "historical"}, "sources": ["call"]}],
            "clues": [{"text": "A saved clue", "sources": ["call"]}],
            "excerpts": [{"key": "selected", "text": "Exact observation \ufffd\u2028 text",
                "historical_locator": "old-file lines 10-12", "current_reference": {
                    "resource": "/current-file", "start_line": 20, "end_line": 22,
                    "status": "unique_content_match", "checked_at": "today", "resource_sha256": "resource-hash"}}],
            "excerpt_locators": {"selected": {"file_path": "/archive/selected.txt", "observed_at": "yesterday"}}}

    def render(self, adapter):
        return adapter.render(self.body, self.source, 2, self.locators,
                              source_index="/archive/sources.json", understanding_index="/archive/understandings.json")

    def test_controls_and_unfolded_tail_are_exact_protocol_values(self):
        original = self.render(CodexCheckpointAdapter())
        candidate = self.render(FactualCodexCheckpointAdapter())
        self.assertEqual(original[:1], candidate[:1])
        self.assertEqual(original[2:], candidate[2:])
        self.assertEqual("assistant", candidate[1]["role"])
        self.assertEqual("commentary", candidate[1]["phase"])

    def test_interpretation_scope_excerpt_and_all_direct_sources_remain(self):
        text = self.render(FactualCodexCheckpointAdapter())[1]["content"][0]["text"]
        for value in ("Existing interpretation", "historical", "Historical result", "A saved clue",
                      "Exact observation \ufffd\u2028 text", "/archive/call.txt", "/archive/selected.txt",
                      "/archive/sources.json", "/archive/understandings.json", "yesterday",
                      "old-file lines 10-12", "/current-file", '"start_line":20', '"end_line":22', "today"):
            self.assertIn(value, text)
        self.assertNotIn("resource-hash", text)

    def test_current_execution_facts_are_visible_and_never_mutate_input(self):
        facts = {"current_workspace": "/actual", "historical_workspace": "/old"}
        adapter = FactualCodexCheckpointAdapter(execution_facts=facts)
        facts["current_workspace"] = "/changed-after-construction"
        before = copy.deepcopy((self.body, self.source, self.locators))
        text = self.render(adapter)[1]["content"][0]["text"]
        self.assertIn('"current_workspace":"/actual"', text)
        self.assertNotIn("changed-after-construction", text)
        self.assertEqual(before, (self.body, self.source, self.locators))

    def test_empty_body_retains_tail_without_fabricated_understanding(self):
        result = FactualCodexCheckpointAdapter().render(None, self.source, 0, self.locators,
            source_index="/archive/sources.json", understanding_index="/archive/understandings.json")
        self.assertEqual(self.source[0]["payload"], result[1])
        self.assertNotIn("Understanding:", result[0]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
