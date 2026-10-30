"""A previous selection bounds inline history, never provenance or cold access."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, Selection, Understanding, Usage, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.generation_frontier import FrontierSpanSelectionGenerator
from wsc.quote_selection import SelectionDraft


def message(role, text):
    return {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}


class FrontierGenerationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-frontier-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: True)
        adapter = CodexCheckpointAdapter()
        self.ids = self.core.ingest(adapter.import_items([
            message("user", "original constraint"), message("assistant", "prior selected observation"),
            message("assistant", "unselected old detail " * 200),
            {"type": "reasoning", "encrypted_content": "opaque-kept-cold"}], thread_id="history", observed_at=["old"] * 4))
        self.previous = self.core.prepare(self.core.capture(), Selection(source_ids=(self.ids[1],),
            new_understandings=(Understanding("prior hypothesis", "hypothesis", (self.ids[2],)),)), producer="fixture")
        self.core.ingest(adapter.import_items([message("user", "reopened with new requirement"),
            message("assistant", "new observation contradicts hypothesis")], thread_id="new", observed_at=["new"] * 2))
        self.snapshot = self.core.capture()

    def selector(self, fn=lambda material: None, **kwargs):
        return FrontierSpanSelectionGenerator(self.core, self.snapshot, self.previous, fn,
                                             archive_directory=self.root / "archive", **kwargs)

    def test_full_and_frontier_only_differ_in_inline_events_and_old_text_is_exactly_recoverable(self):
        material = self.core.material(self.snapshot)
        full = self.selector(mode="full").offer(material)
        frontier = self.selector().offer(material)
        self.assertEqual({k: v for k, v in full.items() if k != "events"},
                         {k: v for k, v in frontier.items() if k != "events"})
        self.assertEqual([1, 2, 5, 6], [e["seq"] for e in frontier["events"]])
        omitted = next(e for e in frontier["source_catalog"] if e["id"] == "s3")
        chunks = [json.loads(line) for line in Path(omitted["span_file"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual("unselected old detail " * 200, "".join(c["text"] for c in chunks))
        self.assertTrue(all(c["observed_at"] == "old" for c in chunks))
        self.assertEqual(material["understandings"][0]["ref"], frontier["understandings"][0]["ref"])
        index = json.loads(Path(frontier["archive"]["source_index"]).read_text(encoding="utf-8"))
        self.assertEqual(set(self.ids) | {e["id"] for e in material["events"][3:]}, set(index))
        self.assertEqual(0, self.core.status()["cursor"])

    def test_model_can_recover_an_omitted_span_and_revise_understanding(self):
        def generate(material):
            source = next(e for e in material["source_catalog"] if e["id"] == "s3")
            span = json.loads(Path(source["span_file"]).read_text(encoding="utf-8").splitlines()[0])
            old = material["understandings"][0]
            return SelectionDraft({"source_ids": ["s3"], "span_refs": [span["ref"]],
                "new_understandings": [{"id": old["id"], "expected_revision": old["revision"],
                    "text": "revised from new observation", "kind": "hypothesis", "sources": ["s6"]}]}, Usage(2, 3, 4))
        view = self.core.generate(self.snapshot, self.selector(generate), producer="offline")
        with self.core.store.connect() as db:
            value = json.loads(db.execute("SELECT data FROM views WHERE id=?", (view,)).fetchone()[0])
        self.assertEqual(2, value["body"]["understandings"][0]["revision"])
        self.assertEqual(self.ids[2], value["body"]["excerpts"][0]["source_id"])
        self.assertEqual(4, self.core.status()["usage"]["totals"]["output"]["known_sum"])

    def test_material_or_prefix_change_rejected_before_callback(self):
        changed = list(self.snapshot.events)
        changed[1] = {**changed[1], "text": "changed"}
        with self.assertRaisesRegex(WSCError, "frontier_snapshot_content_changed"):
            FrontierSpanSelectionGenerator(self.core, replace(self.snapshot, events=tuple(changed)),
                self.previous, lambda m: self.fail("called"), archive_directory=self.root / "wrong")
        material = deepcopy(self.core.material(self.snapshot))
        material["events"][0]["text"] = "different"
        with self.assertRaisesRegex(WSCError, "frontier_generation_material_changed"):
            self.selector(lambda m: self.fail("called"))(material)

    def test_export_denial_preserves_sources_and_records_zero_model_usage(self):
        self.core.access = lambda session, source, action: action != "export"
        with self.assertRaises(WSCError):
            self.core.generate(self.snapshot, self.selector(lambda m: self.fail("called")), producer="offline")
        status = self.core.status()
        self.assertEqual(6, status["source_count"])
        self.assertEqual(0, status["cursor"])
        self.assertEqual(0, status["usage"]["totals"]["output"]["unknown_attempts"])
        self.assertEqual(0, status["usage"]["totals"]["output"]["known_sum"])

    def test_control_change_after_construction_prevents_model_call(self):
        selector = self.selector(lambda m: self.fail("called"))
        self.core.ingest(CodexCheckpointAdapter().import_items([message("user", "new control")], thread_id="late"))
        with self.assertRaisesRegex(WSCError, "control_changed"):
            selector(self.core.material(self.snapshot))


if __name__ == "__main__":
    unittest.main()
