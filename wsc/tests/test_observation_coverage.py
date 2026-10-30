"""Actual prepare/export plus counterexamples where identical text is insufficient."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Selection
from wsc.contracts import Event
from wsc.excerpts import Excerpt
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.covered_codex import CoveredCodexCheckpointAdapter
from wsc.observation_coverage import covered_facts
from wsc.publication import check_evidence
import test_quote_selection as fixtures


class ObservationCoverageTests(unittest.TestCase):
    setUp = fixtures.QuoteSelectionTests.setUp

    def prepare(self, *, selected=True):
        text = self.text
        start = self.text.index(text)
        excerpt = Excerpt("receipt", "result", (), start, start + len(text),
                          sha256(text.encode()).hexdigest(), basis="public_text")
        view = self.core.prepare(self.core.capture(),
            Selection(source_ids=("result",) if selected else (), excerpts=(excerpt,)), producer="fixture")
        op = self.core.stage(view, directory=self.root / "out", adapter=CoveredCodexCheckpointAdapter())
        package = self.core.package(op)
        with self.core.store.connect() as db:
            body = json.loads(db.execute("SELECT data FROM views WHERE id=?", (view,)).fetchone()[0])["body"]
        body["excerpt_locators"] = package["excerpt_evidence"]
        return package, body

    def test_actual_export_keeps_archive_and_ranges_but_omits_duplicate_inline_text(self):
        package, body = self.prepare()
        check_evidence(self.core, package)
        facts = json.loads(package["items"][-1]["content"][0]["text"])
        observation = facts["observations"][0]
        self.assertNotIn("text", observation)
        pointer = observation["inline_coverage"]
        full = facts["historical_excerpts"][pointer["index"]]["text"]
        loc = observation["source"]
        self.assertEqual(body["excerpts"][0]["text"], full[loc["start"]:loc["end"]])
        self.assertEqual(full[loc["start"]:loc["end"]].encode(), Path(loc["file_path"]).read_bytes())
        self.assertEqual("2026-01-01T00:00:00Z", loc["observed_at"])
        self.assertEqual(0, self.core.status()["cursor"])

    def test_unselected_full_source_keeps_excerpt_inline(self):
        package, _ = self.prepare(selected=False)
        observation = json.loads(package["items"][-1]["content"][0]["text"])["observations"][0]
        self.assertIn("text", observation)
        self.assertNotIn("inline_coverage", observation)

    def test_same_text_wrong_identity_range_time_or_basis_never_proves_coverage(self):
        package, body = self.prepare()
        raw = CodexCheckpointAdapter().render(body, self.core.capture().events, 4, package["evidence"],
            source_index=package["source_index"], understanding_index=package["understanding_index"])
        facts = json.loads(raw[-1]["content"][0]["text"])
        for field, value in [("source_id", "other"), ("start", True), ("end", 999),
                             ("observed_at", "today"), ("call_id", "other-call"),
                             ("text_sha256", "0" * 64), ("basis", "payload")]:
            candidate = deepcopy(body)
            candidate["excerpts"][0][field] = value
            with self.subTest(field=field):
                result = covered_facts(candidate, raw, facts)
                self.assertIn("text", result["observations"][0])
        self.assertIn("text", facts["observations"][0])

    def test_rendered_message_text_must_match_producer_text_and_be_one_content_block(self):
        for parts, text, expected in [(["same" * 40], "same" * 40, True),
                (["different"], "same" * 40, False), (["sa" * 40, "me" * 40], "sa" * 40 + "\n" + "me" * 40, False),
                (["same"], "same", False)]:
            source = {"id": "s", "kind": "message", "text": text, "observed_at": "old", "call_id": None,
                "payload": {"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": p} for p in parts]}}
            excerpt = {"key": "q", "source_id": "s", "basis": "public_text", "path": [],
                "start": 0, "end": len(text), "text": text, "text_sha256": sha256(text.encode()).hexdigest(),
                "observed_at": "old", "call_id": None}
            locator = {"source_id": "s", "basis": "public_text", "path": [], "start": 0, "end": len(text),
                       "sha256": excerpt["text_sha256"], "observed_at": "old"}
            facts = {"historical_excerpts": [], "observations": [{"key": "q", "text": text, "source": locator}]}
            value = covered_facts({"sources": [source], "excerpts": [excerpt]}, [source["payload"]], facts)
            self.assertEqual(expected, "inline_coverage" in value["observations"][0])

    def test_controls_tail_understanding_current_reference_and_inputs_are_unchanged(self):
        package, body = self.prepare()
        # Render another tail directly; no extra model operation or publication.
        rows = list(self.core.capture().events)
        rows.append({"seq": 5, "kind": "message", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "new obligation"}]}})
        body["excerpts"][0]["current_reference"] = {"status": "unavailable", "checked_at": "now"}
        before = deepcopy((body, rows, package["evidence"]))
        args = dict(source_index=package["source_index"], understanding_index=package["understanding_index"])
        old = CodexCheckpointAdapter().render(body, rows, 4, package["evidence"], **args)
        new = CoveredCodexCheckpointAdapter().render(body, rows, 4, package["evidence"], **args)
        self.assertEqual(old[0], new[0]); self.assertEqual(old[-1], new[-1])
        a, b = [json.loads(x[1]["content"][0]["text"]) for x in (old, new)]
        self.assertEqual(a["understandings"], b["understandings"])
        self.assertEqual(a["observations"][0]["current_reference"], b["observations"][0]["current_reference"])
        self.assertEqual(before, (body, rows, package["evidence"]))


if __name__ == "__main__":
    unittest.main()
