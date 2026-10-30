from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Event, Usage, WSCError
from wsc.span_boundaries import ranges
from wsc.span_selection import span_material, compile_spans, SpanSelectionGenerator
from wsc.quote_selection import SelectionDraft
from wsc.adapters.factual_codex import FactualCodexCheckpointAdapter
import test_quote_selection as fixtures


class BoundaryTests(unittest.TestCase):
    def test_identifier_is_not_cut_when_it_fits_within_the_limit(self):
        for token in ("abc123ef" * 8, "report_version_2026_10_23", "user@example.test", "-12345.6789e+42"):
            text = "prefix " + " " * 49 + token + " next"
            chunks = [text[a:b] for a, b in ranges(text, 64, policy="word")]
            self.assertEqual(text, "".join(chunks))
            self.assertTrue(any(token in chunk for chunk in chunks))
            self.assertTrue(all(0 < len(chunk) <= 64 for chunk in chunks))

    def test_empty_unicode_and_overlong_runs_preserve_all_characters_with_a_hard_bound(self):
        for text in ("", "x" * 1001, "prefix " + "z" * 2000 + " tail", "中🙂e\u0301\u2028" * 50):
            for size in (1, 7, 64):
                with self.subTest(length=len(text), size=size):
                    chunks = [text[a:b] for a, b in ranges(text, size, policy="word")]
                    self.assertEqual(text, "".join(chunks))
                    self.assertTrue(all(0 < len(chunk) <= size for chunk in chunks))

    def test_fixed_policy_stays_exact_and_invalid_policy_is_rejected_even_without_events(self):
        text = "long_unbroken_identifier plus more"
        self.assertEqual([text[i:i+7] for i in range(0, len(text), 7)],
                         [text[a:b] for a, b in ranges(text, 7)])
        with self.assertRaisesRegex(WSCError, "policy_invalid"):
            span_material({"events": [], "understandings": []}, boundary_policy="unknown")

    def test_changed_boundary_cannot_reinterpret_an_old_reference(self):
        material = {"events": [{"seq": 1, "id": "source", "kind": "message", "role": "assistant",
            "call_id": None, "observed_at": "old", "text": "a " + "identifier" + " end"}], "understandings": []}
        fixed = span_material(material, max_chars=8)["events"][0]["spans"][0]["ref"]
        with self.assertRaisesRegex(WSCError, "missing_or_changed"):
            compile_spans(material, {"span_refs": [fixed]}, max_chars=8, boundary_policy="word")


class BoundaryPublicationTests(unittest.TestCase):
    setUp = fixtures.QuoteSelectionTests.setUp

    def test_generation_and_publication_use_the_same_boundary_and_exact_source(self):
        token = "abcd0123" * 8
        text = " " * 41 + token + " done"
        payload = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
        self.core.ingest([Event("boundary", "message", payload, role="assistant", text=text, observed_at="original")])
        selected = []
        def generate(material):
            span = next(s for s in material["events"][-1]["spans"] if token in s["text"])
            selected.append(span["text"])
            return SelectionDraft({"span_refs": [span["ref"]]}, Usage(1, 0, 2))
        view = self.core.generate(self.core.capture(), SpanSelectionGenerator(generate, max_chars=64,
            boundary_policy="word"), producer="fixture")
        op = self.core.stage(view, directory=self.root / "boundary-export", adapter=FactualCodexCheckpointAdapter())
        locator = next(iter(self.core.package(op)["excerpt_evidence"].values()))
        self.assertEqual(selected[0], Path(locator["file_path"]).read_text(encoding="utf-8"))
        self.assertEqual("original", locator["observed_at"])
        self.assertEqual(2, self.core.status()["usage"]["totals"]["output"]["known_sum"])
