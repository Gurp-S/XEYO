from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]
from native_scope_observation import scope_observation, record_scope, request_scope
from native_rollout_snapshot import parse_rollout
from wsc import Event, Store, WSC, Selection, WSCError
from wsc.adapters.covered_codex import CoveredCodexCheckpointAdapter
from wsc.contracts import digest
from wsc.span_selection import compile_spans


class ScopeObservationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root / "task")),
                        access=lambda *args: True)
        self.core.ingest([Event("user", "message", {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "task"}]}, role="user", text="task")])
        self.context = {"type": "turn_context", "timestamp": "old-observation-time",
                        "payload": {"turn_id": "turn", "cwd": self.core.store.workspace}}
        rows = [{"type": "session_meta", "payload": {"id": "thread"}}, self.context]
        self.snapshot = parse_rollout(("\n".join(json.dumps(r) for r in rows) + "\n").encode())
        self.phase = {"thread_id": "thread", "rollout_sha256": self.snapshot.metadata["sha256"],
                      "usage_completion_evidence": {"turn_id": "turn"}}

    def record(self, *, observed_at="registration-time", workspace=None):
        return record_scope(self.core, self.snapshot, self.phase, workspace or self.root / "generator",
                            observed_at=observed_at)

    def test_historical_clock_and_registration_are_distinct_and_exact(self):
        value = scope_observation(self.snapshot, self.phase, self.root / "generator", observed_at="registration-time")
        self.assertEqual("observation", value.kind)
        self.assertIsNone(value.role)
        self.assertEqual("registration-time", value.observed_at)
        self.assertEqual("old-observation-time", value.payload["evidence"]["native_observed_at"])
        self.assertEqual(2, value.payload["evidence"]["turn_context_line"])
        self.assertEqual(digest(self.context), value.payload["evidence"]["turn_context_sha256"])
        self.assertEqual({"status": "not_registered", "workspace": None}, value.payload["scope"]["continuation_execution"])
        self.assertEqual(self.context, value.payload["native_turn_context"])
        self.assertNotIn("native_turn_context", json.loads(value.text))
        self.assertEqual({k: v for k, v in value.payload.items() if k != "native_turn_context"}, json.loads(value.text))

    def test_replay_is_idempotent_but_new_observation_or_registration_is_not(self):
        first = self.record()
        self.assertEqual(first, self.record())
        self.assertEqual(2, len(self.core.capture().events))
        newer = self.record(observed_at="later-registration-time")
        moved = self.record(workspace=self.root / "another-generator")
        self.assertEqual(3, len({first["source_id"], newer["source_id"], moved["source_id"]}))
        self.assertEqual(4, len(self.core.capture().events))

    def test_wrong_thread_or_archive_rejected_before_ingestion(self):
        for field, value in (("thread_id", "other"), ("rollout_sha256", "0" * 64)):
            original = deepcopy(self.phase)
            self.phase[field] = value
            with self.subTest(field=field), self.assertRaises(WSCError):
                self.record()
            self.assertEqual(1, len(self.core.capture().events))
            self.phase = original

    def test_wrong_task_workspace_cannot_be_rebound_to_generator(self):
        other = WSC(Store(self.root / "other.db", session_id="s", workspace=str(self.root / "generator")),
                    access=lambda *args: True)
        with self.assertRaisesRegex(WSCError, "task_workspace_mismatch"):
            record_scope(other, self.snapshot, self.phase, self.root / "generator", observed_at="now")
        self.assertEqual(0, other.status()["source_count"])

    def test_request_points_to_actual_material_and_rejects_changed_binding(self):
        binding = self.record()
        material = self.core.material(self.core.capture())
        scope = json.loads(material["events"][-1]["text"])["scope"]
        self.assertEqual({"source": "s2"}, request_scope(material, binding, scope))
        for changed in ({**binding, "source": "s1"}, {**binding, "public_value_sha256": "0" * 64}):
            with self.assertRaises(WSCError):
                request_scope(material, changed, scope)
        with self.assertRaises(WSCError):
            request_scope(material, binding, {**scope, "generator_workspace": "other"})

    def test_scope_clue_compiles_and_exports_to_readable_cold_evidence(self):
        binding = self.record()
        material = self.core.material(self.core.capture())
        selection = compile_spans(material, {"clues": [{"text": "Continuation execution is not registered.",
                                                       "sources": [binding["source"]]}]})
        view = self.core.prepare(self.core.capture(), selection, producer="fixture")
        operation = self.core.stage(view, directory=self.root / "export", adapter=CoveredCodexCheckpointAdapter())
        package = self.core.package(operation)
        locator = package["evidence"][binding["source_id"]]
        payload = json.loads(Path(locator["file_path"]).read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in payload.items() if k != "native_turn_context"},
                         json.loads(Path(locator["readable_path"]).read_text(encoding="utf-8")))
        self.assertEqual(self.context, payload["native_turn_context"])
        self.assertEqual(payload["evidence"]["turn_context_sha256"], digest(payload["native_turn_context"]))
        self.assertEqual("not_registered", payload["scope"]["continuation_execution"]["status"])
        self.assertEqual("registration-time", locator["observed_at"])
        self.assertEqual(0, self.core.status()["cursor"])

    def test_scope_observation_uses_the_same_export_authorization(self):
        binding = self.record()
        view = self.core.prepare(self.core.capture(), Selection(clues=({"text": "fact", "sources": [binding["source_id"]]},)),
                                 producer="fixture")
        self.core.access = lambda session, source, action: not (source == binding["source_id"] and action == "export")
        with self.assertRaises(WSCError):
            self.core.stage(view, directory=self.root / "denied", adapter=CoveredCodexCheckpointAdapter())
