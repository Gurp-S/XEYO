"""Admission binds draft and material to one durable, paid native turn."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]
from native_evidence import FIELDS, file_hash, usage
from native_generated_selection import verify
from native_rollout_snapshot import capture_rollout
from native_usage_boundary import completion_evidence
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import encode
from wsc.projection import public_material
from wsc.span_selection import compile_spans, span_material


class NativeGenerationBindingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-generated-binding-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.batch = CodexCheckpointAdapter().import_items([{"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "original task"}]}], thread_id="source")
        prefix = [{**asdict(e), "seq": i + 1} for i, e in enumerate(self.batch)]
        self.material = {"session_id": "generator", "source_boundary": 1, **public_material(prefix, [])}
        self.draft = {"source_ids": ["s1"]}
        self.text = encode(self.draft)
        request = encode({"operation": "working_state_selection", "material": span_material(self.material)})
        counts = dict.fromkeys(FIELDS, 0)
        counts.update(input_tokens=10, output_tokens=2, total_tokens=12)
        self.rows = [
            {"type": "session_meta", "payload": {"id": "thread"}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
            {"type": "turn_context", "payload": {"turn_id": "turn"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": request}]}},
            {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": "thread",
                "turn_id": "turn", "item": {"type": "UserMessage", "content": [{"type": "text", "text": request}]}}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "id": "final",
                "phase": "final_answer", "content": [{"type": "output_text", "text": self.text}]}},
            {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": "thread", "turn_id": "turn",
                "item": {"type": "AgentMessage", "id": "final", "phase": "final_answer",
                         "content": [{"type": "Text", "text": self.text}]}}},
            {"type": "token_usage_record", "payload": {"thread_id": "thread", "turn_id": "turn",
                "response_id": "r1", "usage": counts, "turn_token_usage": counts}},
            {"type": "event_msg", "payload": {"type": "token_count",
                "info": {"total_token_usage": counts, "last_token_usage": counts}}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn", "last_agent_message": self.text}},
        ]

    def admit(self, *, draft=None):
        draft = self.draft if draft is None else draft
        rollout = self.root / "rollout.jsonl"
        rollout.write_text("".join(encode(r) + "\n" for r in self.rows), encoding="utf-8")
        snapshot = capture_rollout(rollout)
        receipts = usage(snapshot.rows, "thread", line_numbers=snapshot.line_numbers)
        phase = {"completed": True, "usage_complete": True, "failure": None, "thread_id": "thread",
            "finals": [{"type": "agentMessage", "id": "final", "phase": "final_answer", "text": encode(draft)}],
            "receipts": receipts, "rollout_sha256": snapshot.metadata["sha256"],
            "usage_completion_evidence": completion_evidence(snapshot, receipts, turn_id="turn", compact=False)}
        for name, value in (("material", self.material), ("draft", draft), ("phase", phase)):
            (self.root / (name + ".json")).write_text(encode(value), encoding="utf-8")
        refs = {key: {"path": str(self.root / name), "sha256": file_hash(self.root / name)}
                for key, name in [(k, k + ".json") for k in ("material", "draft", "phase")] + [("rollout", "rollout.jsonl")]}
        plan = {"generated_selection": {"format": "bound_spans_v1", "max_chars": 1024, "evidence": refs}}
        return verify(plan, self.batch, compile_spans(self.material, draft))

    def test_unchanged_paid_turn_is_accepted(self):
        self.assertTrue(self.admit()["selection_replayed_exactly"])

    def test_native_completion_event_before_response_item_is_accepted(self):
        self.rows[5], self.rows[6] = self.rows[6], self.rows[5]
        self.assertTrue(self.admit()["selection_replayed_exactly"])

    def test_zero_inference_import_context_before_turn_is_accepted(self):
        self.rows.insert(1, {"type": "turn_context", "payload": {"turn_id": "auto-compact-0"}})
        self.assertTrue(self.admit()["selection_replayed_exactly"])

    def test_rehashed_draft_and_phase_cannot_replace_actual_final(self):
        with self.assertRaisesRegex(ValueError, "generated_selection_.*"):
            self.admit(draft={"source_ids": []})

    def test_changed_submitted_material_rejected_even_with_rehashed_receipts(self):
        for field in ("response", "turn"):
            with self.subTest(field=field):
                before = deepcopy(self.rows)
                target = self.rows[3]["payload"] if field == "response" else self.rows[4]["payload"]["item"]
                value = json.loads(target["content"][0]["text"])
                value["material"]["events"][0]["spans"][0]["text"] = "different task"
                target["content"][0]["text"] = encode(value)
                with self.assertRaisesRegex(ValueError, "generated_selection_.*"):
                    self.admit()
                self.rows = before

    def test_extra_turn_or_duplicate_final_does_not_borrow_paid_receipts(self):
        for row in ({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "other"}},
                    self.rows[5]):
            with self.subTest(row=row["type"]):
                self.rows.insert(5, deepcopy(row))
                with self.assertRaisesRegex(ValueError, "generated_selection_.*"):
                    self.admit()
                self.rows.pop(5)

    def test_final_text_must_match_completion_and_item_identity(self):
        for index, key, value in [(9, "last_agent_message", "{}"), (6, "turn_id", "other")]:
            with self.subTest(key=key):
                before = deepcopy(self.rows)
                self.rows[index]["payload"][key] = value
                with self.assertRaisesRegex(ValueError, "generated_selection_.*"):
                    self.admit()
                self.rows = before


if __name__ == "__main__":
    unittest.main()
