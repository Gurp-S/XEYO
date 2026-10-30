"""Facts match real preparation/export behavior without becoming semantic policy."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Generated, Selection, Limits, WSCError
from wsc.contracts import Event, encode
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.selection_facts import describe
from wsc.quote_selection import selection_material


class SelectionFactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = WSC(Store(self.root / "s.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: True)
        self.core.ingest([
            Event("u", "message", {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "original constraint"}]}, role="user", text="original constraint"),
            Event("e", "observation", {"raw": "larger than public"}, text="旧观察", observed_at="yesterday"),
            Event("opaque", "opaque", {"encrypted_content": "not-public"})])

    def test_default_generation_does_not_add_candidate_facts(self):
        seen = []
        self.core.generate(self.core.capture(), lambda m: seen.append(m) or Generated(Selection()), producer="fixture")
        self.assertNotIn("selection_facts", seen[0])

    def test_opt_in_costs_match_actual_body_and_mandatory_records_cannot_be_forged(self):
        snapshot = self.core.capture()
        seen = []
        view = self.core.generate(replace(snapshot, events=()),
            lambda m: seen.append(m) or Generated(Selection(source_ids=("e", "e"))),
            producer="fixture", include_selection_facts=True)
        facts = seen[0]["selection_facts"]
        self.assertTrue(facts["source_records"]["u"]["automatically_retained"])
        self.assertFalse(facts["source_records"]["e"]["automatically_retained"])
        self.assertEqual(len("旧观察".encode()), facts["source_records"]["e"]["public_text_utf8_bytes"])
        with self.core.store.connect() as db:
            body = json.loads(db.execute("SELECT data FROM views WHERE id=?", (view,)).fetchone()[0])["body"]
        self.assertEqual(facts["mandatory_empty_view_bytes"] + 1 +
                         facts["source_records"]["e"]["serialized_record_bytes"], len(encode(body).encode()))
        self.assertNotIn("opaque", facts["source_records"])
        self.assertNotIn("not-public", encode(seen[0]))

    def test_aliases_bind_the_same_cost_records_without_mutating_original(self):
        snapshot = self.core.capture()
        material = self.core.material(snapshot)
        material["selection_facts"] = describe(snapshot.events, 32768)
        before = encode(material)
        offered = selection_material(material)
        self.assertEqual({"s1", "s2"}, set(offered["selection_facts"]["source_records"]))
        self.assertEqual(material["selection_facts"]["source_records"]["e"],
                         offered["selection_facts"]["source_records"]["s2"])
        self.assertEqual(before, encode(material))

    def test_unselected_source_is_in_export_but_never_claims_host_installation(self):
        view = self.core.generate(self.core.capture(), lambda m: Generated(Selection()),
                                 producer="fixture", include_selection_facts=True)
        op = self.core.stage(view, directory=self.root / "exports", adapter=CodexCheckpointAdapter())
        package = self.core.package(op)
        self.assertEqual({"u", "e", "opaque"}, set(package["evidence"]))
        self.assertEqual(0, self.core.status()["cursor"])
        self.assertTrue(all(Path(v["file_path"]).exists() for v in package["evidence"].values()))

    def test_fact_overhead_counts_toward_material_budget_before_model_call(self):
        snapshot = self.core.capture()
        raw_bytes = len(encode(self.core.material(snapshot)).encode())
        called = []
        with self.assertRaisesRegex(WSCError, "generation_material_byte_budget_exhausted"):
            self.core.generate(snapshot, lambda m: called.append(m), producer="fixture",
                limits=Limits(max_material_bytes=raw_bytes), include_selection_facts=True)
        self.assertEqual([], called)
        self.assertEqual([], self.core.status()["usage"]["attempts"])

    def test_new_control_during_selection_still_invalidates_the_result(self):
        def generate(material):
            self.core.ingest([Event("new", "control", {}, text="new scope", control=True)])
            return Generated(Selection())
        with self.assertRaisesRegex(WSCError, "control_changed"):
            self.core.generate(self.core.capture(), generate, producer="fixture", include_selection_facts=True)


if __name__ == "__main__":
    unittest.main()
