"""Bound choices preserve exact bytes without making the model copy evidence."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Usage, Limits, WSCError
from wsc.contracts import encode
from wsc.quote_selection import SelectionDraft
from wsc.span_selection import span_material, compile_spans, SpanSelectionGenerator
from wsc.adapters.factual_codex import FactualCodexCheckpointAdapter
from wsc.selection_facts import describe
import test_quote_selection as quote_fixtures


class SpanSelectionTests(unittest.TestCase):
    # Reuse only fixture construction, not its test methods.
    setUp = quote_fixtures.QuoteSelectionTests.setUp

    def test_span_facts_match_output_fields_without_mutating_quote_facts(self):
        snapshot = self.core.capture()
        material = {**self.core.material(snapshot), 'selection_facts': describe(snapshot.events, 32768)}
        before = encode(material)
        offered = span_material(material)
        effects = offered['selection_facts']['selection_effects']
        self.assertIn('span_refs', effects)
        self.assertNotIn('quotes', effects)
        self.assertIn('quotes', material['selection_facts']['selection_effects'])
        self.assertEqual(before, encode(material))
        self.assertEqual(material['selection_facts']['mandatory_empty_view_bytes'],
                         offered['selection_facts']['mandatory_empty_view_bytes'])

    def test_every_public_character_is_offered_once_without_opaque_content(self):
        material = self.core.material(self.core.capture())
        offered = span_material(material, max_chars=7)
        for before, after in zip(material["events"], offered["events"]):
            self.assertEqual(before["text"], "".join(s["text"] for s in after["spans"]))
            self.assertEqual(before["observed_at"], after["observed_at"])
            self.assertEqual(before["call_id"], after["call_id"])
        self.assertNotIn("SECRET", encode(offered))

    def test_duplicate_text_has_distinct_selectable_occurrences(self):
        material = self.core.material(self.core.capture())
        material["events"][-1]["text"] = "samesame"
        spans = span_material(material, max_chars=4)["events"][-1]["spans"]
        self.assertNotEqual(spans[0]["ref"], spans[1]["ref"])
        selection = compile_spans(material, {"span_refs": [spans[1]["ref"]]}, max_chars=4)
        self.assertEqual((4, 8), (selection.excerpts[0].start, selection.excerpts[0].end))

    def test_changed_source_or_partition_does_not_reinterpret_an_old_handle(self):
        material = self.core.material(self.core.capture())
        ref = span_material(material, max_chars=8)["events"][-1]["spans"][0]["ref"]
        for change in ("identity", "text", "partition"):
            changed = deepcopy(material)
            if change == "identity": changed["events"][-1]["id"] = "other-observation"
            if change == "text": changed["events"][-1]["text"] = "different" + changed["events"][-1]["text"]
            with self.subTest(change=change), self.assertRaisesRegex(WSCError, "missing_or_changed"):
                compile_spans(changed, {"span_refs": [ref]}, max_chars=9 if change == "partition" else 8)

    def test_paraphrase_cannot_enter_the_span_selection_contract(self):
        material = self.core.material(self.core.capture())
        with self.assertRaisesRegex(WSCError, "shape_invalid"):
            compile_spans(material, {"quotes": [{"text": "plausible paraphrase"}]})
        with self.assertRaisesRegex(WSCError, "missing_or_changed"):
            compile_spans(material, {"span_refs": ["invented span"]})

    def test_real_generate_export_preserves_selected_unicode_and_observation_time(self):
        selected = []
        def model(material):
            self.assertIn('span_refs', material['selection_facts']['selection_effects'])
            self.assertNotIn('quotes', material['selection_facts']['selection_effects'])
            span = material["events"][-1]["spans"][1]
            selected.append(span["text"])
            return SelectionDraft({"span_refs": [span["ref"], span["ref"]]}, Usage(5, 0, 2))
        view = self.core.generate(self.core.capture(), SpanSelectionGenerator(model, max_chars=19),
                                 producer="offline_fixture", include_selection_facts=True)
        with self.core.store.connect() as db:
            body = json.loads(db.execute('SELECT data FROM views WHERE id=?', (view,)).fetchone()[0])['body']
        self.assertTrue(all(r['role'] in {'user', 'system', 'developer'} for r in body['sources']))
        self.assertTrue(body['excerpts'])
        op = self.core.stage(view, directory=self.root / "export", adapter=FactualCodexCheckpointAdapter())
        excerpts = self.core.package(op)["excerpt_evidence"]
        self.assertEqual(1, len(excerpts))
        value = next(iter(excerpts.values()))
        self.assertEqual(selected[0].encode(), Path(value["file_path"]).read_bytes())
        self.assertEqual("2026-01-01T00:00:00Z", value["observed_at"])

    def test_expanded_offer_budget_stops_before_call_with_known_zero_model_usage(self):
        called = []
        with self.assertRaisesRegex(WSCError, "span_material_byte_budget_exhausted"):
            self.core.generate(self.core.capture(), SpanSelectionGenerator(lambda m: called.append(m),
                max_material_bytes=1), producer="offline_fixture")
        self.assertEqual([], called)
        totals = self.core.status()["usage"]["totals"]
        self.assertEqual({"known_sum": 0, "unknown_attempts": 0}, totals["output"])


if __name__ == "__main__":
    unittest.main()
