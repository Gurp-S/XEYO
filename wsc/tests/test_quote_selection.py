"""Opt-in model drafts reach real generation, snapshot and export boundaries."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Usage, Understanding, Limits, Selection, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.factual_codex import FactualCodexCheckpointAdapter
from wsc.contracts import Event
from wsc.excerpts import Excerpt
from wsc.publication import check_evidence
from wsc.quote_selection import (SelectionDraft, QuoteSelectionGenerator,
                                 compile_selection, selection_material)


class QuoteSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = True
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: self.allowed)
        self.text = "old location\r\nH1: 18/18; H2: unknown\nvalid \ufffd \u2028 \U0001f50d\nsame same"
        self.core.ingest([
            Event("u", "message", {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "Continue current H2"}]}, role="user", text="Continue current H2"),
            Event("read", "call", {"private_unoffered_field": "SECRET"}, call_id="call", text="read"),
            Event("result", "result", {"carrier": "separate representation"}, call_id="call",
                  text=self.text, observed_at="2026-01-01T00:00:00Z"),
            Event("opaque", "opaque", {"encrypted_content": "SECRET"})])
        self.core.presented("observed", ("result",), receiver="offline_test")
        self.draft = {"new_understandings": [{"text": "Historical H1 result does not verify H2.",
            "kind": "diagnosis", "sources": ["s3"], "scope": {"current_applicability": "unknown"}}],
            "quotes": [{"key": "receipt", "source_id": "s3", "text": "H1: 18/18; H2: unknown"}]}

    def generate(self, draft=None, callback=None):
        snapshot = self.core.capture()
        def generate(material):
            if callback:
                callback(material)
            return SelectionDraft(deepcopy(draft if draft is not None else self.draft), Usage(10, 20, 5))
        return self.core.generate(snapshot, QuoteSelectionGenerator(generate), producer="offline_model_fixture")

    def test_generate_compile_export_reopen_preserves_exact_text_time_and_usage(self):
        view = self.generate()
        reopened = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                       access=lambda *args: True)
        operation = reopened.stage(view, directory=self.root / "exports", adapter=CodexCheckpointAdapter())
        package = reopened.package(operation)
        check_evidence(reopened, package)
        excerpt = package["excerpt_evidence"]["receipt"]
        text = self.draft["quotes"][0]["text"]
        self.assertEqual(text.encode(), Path(excerpt["file_path"]).read_bytes())
        self.assertEqual(sha256(text.encode()).hexdigest(), excerpt["sha256"])
        self.assertEqual("public_text", excerpt["basis"])
        self.assertEqual("result", excerpt["source_id"])
        self.assertEqual("2026-01-01T00:00:00Z", excerpt["observed_at"])
        self.assertEqual(0, reopened.status()["cursor"])
        with reopened.store.connect() as db:
            data = json.loads(db.execute("SELECT data FROM views WHERE id=?", (view,)).fetchone()[0])
            self.assertEqual(["result"], data["body"]["understandings"][0]["sources"])
            usage = json.loads(db.execute("SELECT data FROM usage").fetchone()[0])
        self.assertEqual(10, usage["input_uncached"])
        self.assertEqual(5, usage["output"])

    def test_material_aliases_preserve_public_facts_without_raw_payload_or_opaque(self):
        material = self.core.material(self.core.capture())
        offered = selection_material(material)
        self.assertEqual(["s1", "s2", "s3"], [e["id"] for e in offered["events"]])
        self.assertEqual(self.text, offered["events"][-1]["text"])
        self.assertNotIn("SECRET", json.dumps(offered))
        self.assertEqual("result", material["events"][-1]["id"])

    def test_quote_without_historical_location_exports_through_factual_adapter(self):
        view = self.generate()
        op = self.core.stage(view, directory=self.root / "factual", adapter=FactualCodexCheckpointAdapter())
        package = self.core.package(op)
        check_evidence(self.core, package)
        text = package["items"][-1]["content"][0]["text"]
        self.assertIn(self.draft["quotes"][0]["text"], text)
        self.assertIn("2026-01-01T00:00:00Z", text)
        self.assertNotIn("Historical location:", text)

    def test_invalid_selection_retains_known_generation_cost_and_does_not_retry(self):
        draft = deepcopy(self.draft)
        draft["quotes"][0]["text"] = "not observed"
        with self.assertRaisesRegex(WSCError, "quote_text_missing"):
            self.generate(draft)
        with self.core.store.connect() as db:
            rows = list(db.execute("SELECT status,data FROM usage"))
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM views").fetchone()[0])
        self.assertEqual(1, len(rows))
        self.assertEqual("failed", rows[0]["status"])
        self.assertEqual(5, json.loads(rows[0]["data"])["output"])
        with self.assertRaisesRegex(WSCError, "generation_budget_exhausted"):
            self.generate()

    def test_changed_control_during_model_call_rejects_old_candidate(self):
        def change(material):
            self.core.ingest([Event("new", "control", {}, text="new scope", control=True)])
        with self.assertRaisesRegex(WSCError, "control_changed"):
            self.generate(callback=change)
        self.assertEqual((), self.core.capture().understandings)

    def test_revoked_permission_during_model_call_rejects_quote_and_rolls_back_understanding(self):
        with self.assertRaisesRegex(WSCError, "Permission denied"):
            self.generate(callback=lambda material: setattr(self, "allowed", False))
        self.assertEqual((), self.core.capture().understandings)

    def test_missing_ambiguous_overlapping_and_normalized_text_are_not_guessed(self):
        material = self.core.material(self.core.capture())
        for text, reason in [("same", "ambiguous"), ("old location\nH1", "missing"),
                             ("H1: 18/18; H2: passed", "missing")]:
            draft = {"quotes": [{"key": "x", "source_id": "s3", "text": text}]}
            with self.subTest(text=text), self.assertRaisesRegex(WSCError, reason):
                compile_selection(material, draft)
        material["events"][-1]["text"] = "aaa"
        with self.assertRaisesRegex(WSCError, "ambiguous"):
            compile_selection(material, {"quotes": [{"key": "x", "source_id": "s3", "text": "aa"}]})

    def test_unicode_uses_character_offsets_and_utf8_hash_without_normalization(self):
        quote = "valid \ufffd \u2028 \U0001f50d"
        selected = compile_selection(self.core.material(self.core.capture()),
            {"quotes": [{"key": "unicode", "source_id": "s3", "text": quote}]})
        excerpt = selected.excerpts[0]
        self.assertEqual(quote, self.text[excerpt.start:excerpt.end])
        self.assertEqual(sha256(quote.encode()).hexdigest(), excerpt.text_sha256)
        self.core.prepare(self.core.capture(), selected, producer="offline_fixture")

    def test_unoffered_sources_live_paths_and_duplicate_quote_names_are_rejected(self):
        material = self.core.material(self.core.capture())
        for draft, reason in [({"source_ids": ["s4"]}, "source_missing"),
                ({"source_ids": ["result"]}, "source_missing"),
                ({"quotes": [dict(self.draft["quotes"][0], current_resource="C:/secret")]}, "shape_invalid"),
                ({"quotes": self.draft["quotes"] * 2}, "duplicate"),
                ({"quotes": [{"key": "x", "source_id": [], "text": "x"}]}, "list_invalid")]:
            with self.subTest(draft=draft), self.assertRaisesRegex(WSCError, reason):
                compile_selection(material, draft)

    def test_existing_understanding_revision_is_selected_explicitly_and_can_be_revised(self):
        old = self.core.remember(Understanding("Old interpretation", "hypothesis", ("result",)), producer="m")
        material = self.core.material(self.core.capture())
        self.assertEqual(["s3"], selection_material(material)["understandings"][0]["sources"])
        selected = compile_selection(material, {"understanding_refs": [old["ref"]],
            "new_understandings": [{"id": old["id"], "expected_revision": 1,
                "text": "Revised interpretation", "kind": "hypothesis", "sources": ["s3"]}]})
        self.core.prepare(self.core.capture(), selected, producer="m")
        self.assertEqual([1, 2], [r["revision"] for r in self.core.capture().understandings])

    def test_public_text_basis_cannot_be_confused_with_payload_or_path(self):
        selected = compile_selection(self.core.material(self.core.capture()), self.draft)
        original = selected.excerpts[0]
        for item, reason in [(replace(original, basis="payload"), "value_not_text"),
                             (replace(original, path=("carrier",)), "path_invalid"),
                             (replace(original, basis=[]), "basis_invalid")]:
            with self.subTest(reason=reason), self.assertRaisesRegex(WSCError, reason):
                self.core.prepare(self.core.capture(), Selection(excerpts=(item,)), producer="m")

    def test_view_byte_limit_remains_authoritative(self):
        selected = compile_selection(self.core.material(self.core.capture()), self.draft)
        with self.assertRaisesRegex(WSCError, "view_byte_budget_exhausted"):
            self.core.prepare(self.core.capture(), selected, producer="m", limits=Limits(max_view_bytes=10))
        self.assertEqual((), self.core.capture().understandings)


if __name__ == "__main__":
    unittest.main()
