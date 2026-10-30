"""Content-bound observation reuse through real prepare/export/install boundaries."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Selection, Understanding, Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import WSCError, encode
from wsc.excerpts import Excerpt
from wsc.generation import selection_from_json
from wsc.publication import check_evidence


class EvidenceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = True
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace="copy"),
                        access=lambda *args: self.allowed)
        self.adapter = CodexCheckpointAdapter()
        self.observation = "before\nMEMORY old task: valid evidence\nafter"
        self.items = [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Repair H2"}]},
            {"type": "function_call", "name": "Read", "call_id": "read", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "read", "output": json.dumps({"text": self.observation})},
            {"type": "reasoning", "encrypted_content": "opaque"}]
        self.batch = self.adapter.import_items(self.items, thread_id="t",
            observed_at=["2026-01-01T01:00:00Z"] * len(self.items))
        self.core.ingest(self.batch)
        self.core.presented("old-request", (self.batch[2].id,), receiver="historical-model")
        self.text = "MEMORY old task: valid evidence"
        self.slice = Excerpt("memory", self.batch[2].id, ("output", None, "text"), 7,
            7 + len(self.text), sha256(self.text.encode()).hexdigest(), "MEMORY.md:100-100")

    def selection(self, item=None):
        return Selection(excerpts=(item or self.slice,), new_understandings=(Understanding(
            "H1 passed; H2 applicability unknown.", "historical", (self.batch[2].id,)),))

    def package(self):
        view = self.core.prepare(self.core.capture(), self.selection(), producer="model")
        op = self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        return self.core.package(op)

    def test_live_lines_moved_or_deleted_do_not_change_archived_evidence(self):
        live = self.root / "MEMORY.md"
        live.write_text("unrelated new task\n" * 100, encoding="utf-8")
        p = self.package()
        live.unlink()
        check_evidence(self.core, p)
        item = p["excerpt_evidence"]["memory"]
        self.assertEqual(self.text, Path(item["file_path"]).read_text(encoding="utf-8"))
        self.assertEqual("2026-01-01T01:00:00Z", item["observed_at"])
        self.assertEqual(self.items[0], p["items"][0])
        view = json.loads(p["items"][-1]["content"][0]["text"])
        self.assertEqual(self.text, view["observations"][0]["text"])
        self.assertIn("H2 applicability unknown", view["understandings"][0]["text"])
        self.assertNotIn("unrelated new task", encode(p["items"]))
        self.assertEqual(0, self.core.status()["cursor"])

    def test_tampered_or_missing_archive_is_rejected_before_install(self):
        p = self.package()
        path = Path(p["excerpt_evidence"]["memory"]["file_path"])
        path.write_text("different evidence", encoding="utf-8")
        with self.assertRaisesRegex(WSCError, "excerpt_changed_or_missing"):
            check_evidence(self.core, p)
        path.unlink()
        with self.assertRaisesRegex(WSCError, "excerpt_changed_or_missing"):
            check_evidence(self.core, p)

    def test_wrong_content_range_path_and_opaque_source_fail_atomically(self):
        cases = [(replace(self.slice, text_sha256="0" * 64), "content_mismatch"),
                 (replace(self.slice, end=9999), "range_invalid"),
                 (replace(self.slice, start=True), "range_invalid"),
                 (replace(self.slice, path=("missing",)), "key_unavailable"),
                 (replace(self.slice, path=("output", None, "text", None)), "json_unavailable"),
                 (replace(self.slice, source_id="missing"), "source_missing"),
                 (replace(self.slice, source_id=self.batch[3].id), "opaque_excerpt")]
        snap = self.core.capture()
        for item, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(WSCError, reason):
                self.core.prepare(snap, self.selection(item), producer="model")
        self.assertEqual((), self.core.capture().understandings)

    def test_content_changed_under_same_source_identity_is_not_relocated_by_similarity(self):
        changed = deepcopy(self.items[2])
        changed["output"] = json.dumps({"text": self.observation.replace("valid", "wrong")})
        with self.assertRaisesRegex(WSCError, "source_identity_conflict"):
            self.core.ingest([replace(self.batch[2], payload=changed)])
        p = self.package()
        self.assertEqual(self.text, Path(p["excerpt_evidence"]["memory"]["file_path"]).read_text())

    def test_repeated_identical_text_uses_explicit_range_and_new_version_remains_distinct(self):
        items = [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "same\nchanged\nsame"}]}]
        event = self.adapter.import_items(items, thread_id="new", observed_at=["2026-02-01"])[0]
        self.core.ingest([event])
        e = Excerpt("second", event.id, ("content", 0, "text"), 13, 17, sha256(b"same").hexdigest())
        view = self.core.prepare(self.core.capture(), Selection(excerpts=(e,)), producer="model")
        op = self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        loc = self.core.package(op)["excerpt_evidence"]["second"]
        self.assertEqual(13, loc["start"])
        self.assertEqual("2026-02-01", loc["observed_at"])

    def test_permission_budget_and_duplicate_keys_are_enforced(self):
        snap = self.core.capture()
        with self.assertRaisesRegex(WSCError, "view_byte_budget"):
            self.core.prepare(snap, self.selection(), producer="model", limits=Limits(max_view_bytes=10))
        with self.assertRaisesRegex(WSCError, "duplicate"):
            self.core.prepare(snap, Selection(excerpts=(self.slice, self.slice)), producer="model")
        self.allowed = False
        with self.assertRaisesRegex(WSCError, "Permission denied"):
            self.core.prepare(snap, self.selection(), producer="model")

    def test_json_selection_transport_preserves_exact_bindings(self):
        from dataclasses import asdict
        selected = selection_from_json({"excerpts": [asdict(self.slice)]})
        view = self.core.prepare(self.core.capture(), selected, producer="model")
        self.assertIsInstance(view, str)
        with self.assertRaisesRegex(WSCError, "excerpt_shape"):
            selection_from_json({"excerpts": [{"key": "missing bindings"}]})

    def test_opt_in_current_reference_is_separate_from_historical_observation(self):
        live = self.root / "MEMORY.md"
        live.write_bytes(("new heading\n" + self.text + "\n").encode())
        item = replace(self.slice, current_resource=str(live),
                       current_resource_sha256=sha256(live.read_bytes()).hexdigest())
        view = self.core.prepare(self.core.capture(), self.selection(item), producer="model")
        op = self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        package = self.core.package(op)
        hot = json.loads(package["items"][-1]["content"][0]["text"])["observations"][0]
        self.assertEqual(2, hot["current_reference"]["start_line"])
        self.assertEqual("2026-01-01T01:00:00Z", hot["source"]["observed_at"])
        self.assertEqual("MEMORY.md:100-100", hot["historical_locator"])
        check_evidence(self.core, package)
        live.write_bytes(b"changed")
        with self.assertRaisesRegex(WSCError, "reference_resource_changed"):
            check_evidence(self.core, package)

    def test_deleted_runtime_artifact_invalidates_live_reference_but_preserves_history(self):
        live = self.root / '.codex-vitest-preload.mjs'
        live.write_text(self.text,encoding='utf-8')
        item = replace(self.slice,current_resource=str(live),
                       current_resource_sha256=sha256(live.read_bytes()).hexdigest())
        view = self.core.prepare(self.core.capture(),self.selection(item),producer='model')
        op = self.core.stage(view,directory=self.root/'exports',adapter=self.adapter)
        package = self.core.package(op)
        check_evidence(self.core,package)
        live.unlink()
        with self.assertRaisesRegex(WSCError,'reference_resource_changed'):
            check_evidence(self.core,package)
        archived = Path(package['excerpt_evidence']['memory']['file_path'])
        self.assertEqual(self.text,archived.read_text(encoding='utf-8'))
        self.assertFalse(package['current_reference_bindings'][0]['historical_observation_retimed'])


if __name__ == "__main__":
    unittest.main()
