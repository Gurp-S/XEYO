"""Selection/timestamp admission is source-bound and makes no live model calls."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import run_native_pair  # Establish the local independent package path.
from native_candidate_evidence import selected_material
from native_c_qualification import fingerprint
from native_evidence import digest, file_hash, save
from wsc.adapters.codex import CodexCheckpointAdapter


class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.items = [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Historical result; current applicability unknown"}]}]
        self.rollout = self.root / "rollout.jsonl"
        self.rollout.write_text(json.dumps({"type": "response_item", "payload": self.items[0],
            "timestamp": "2026-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
        self.source = {"items": self.items, "thread_id": "test", "rollout_path": str(self.rollout),
                       "rollout_sha256": file_hash(self.rollout)}
        event = CodexCheckpointAdapter().import_items(self.items, thread_id="test")[0]
        text = self.items[0]["content"][0]["text"]
        self.plan = {"source_items_sha256": digest(self.items), "required_observations": ["old"],
            "selection": {"new_understandings": [{"text": "H1 only", "kind": "historical", "sources": [event.id]}],
                "excerpts": [{"key": "old", "source_id": event.id, "path": ["content", 0, "text"],
                    "start": 0, "end": len(text), "text_sha256": sha256(text.encode()).hexdigest()}]}}
        self.plan_path = self.root / "plan.json"
        save(self.plan_path, self.plan)

    def test_source_times_are_historical_and_required_observations_survive(self):
        _, batch, _, resolved = selected_material(self.plan_path, self.source)
        self.assertEqual("2026-01-01T00:00:00Z", batch[0].observed_at)
        self.assertEqual(batch[0].observed_at, resolved[0]["observed_at"])
        changed = deepcopy(self.plan)
        changed["required_observations"].append("missing")
        save(self.root / "missing.json", changed)
        with self.assertRaisesRegex(ValueError, "required_observation_missing"):
            selected_material(self.root / "missing.json", self.source)

    def test_later_or_different_source_and_timestamp_records_cannot_replace_checkpoint(self):
        changed = deepcopy(self.source)
        changed["items"].append(self.items[0])
        with self.assertRaisesRegex(ValueError, "selection_source_boundary_changed"):
            selected_material(self.plan_path, changed)
        self.rollout.write_text(self.rollout.read_text().replace("2026-01-01", "2026-02-02"))
        with self.assertRaisesRegex(ValueError, "source_rollout_changed"):
            selected_material(self.plan_path, self.source)

    def test_selection_change_invalidates_qualification_fingerprint(self):
        reg = {k: None for k in ("model", "effort", "settings", "dynamic_tools", "pins", "shared_request",
            "raw_source_items_sha256", "admission_warmup_threads", "orchestration")}
        reg.update(initial_manifest={}, candidate_selection={"sha256": "old"}, caps={
            "responses_per_arm_including_compaction": 10, "wall_seconds_per_arm": 480,
            "model_requested_checks_per_arm": 3})
        before = fingerprint(reg)
        reg["candidate_selection"]["sha256"] = "new"
        self.assertNotEqual(before, fingerprint(reg))


if __name__ == "__main__":
    unittest.main()
