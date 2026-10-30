"""An ended RPC turn alone cannot prove that its archived receipts are complete."""
import copy
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_evidence import FIELDS, records
from native_rpc import NativeRPC
from run_native_pair import phase
from native_rollout_snapshot import capture_rollout, parse_rollout
from native_usage_boundary import completion_evidence
from native_evidence import usage


def receipt(response="r1", amount=1):
    value = dict.fromkeys(FIELDS, 0)
    value.update(input_tokens=10, output_tokens=2, total_tokens=12)
    return {"type": "token_usage_record", "payload": {
        "thread_id": "t1", "turn_id": "turn1", "response_id": response,
        "usage": value, "turn_token_usage": {k: v * amount for k, v in value.items()}}}


def finished_rows():
    first, last = receipt(), receipt("r2", 2)
    return [first, last, {"type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": last["payload"]["turn_token_usage"],
        "last_token_usage": last["payload"]["usage"]}}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn1"}}]


class FinishedServer:
    def call(self, *args, **kwargs):
        return {"turn": {"id": "turn1"}}

    def event(self, *args, **kwargs):
        return {"method": "turn/completed", "params": {
            "threadId": "t1", "turn": {"id": "turn1", "status": "completed"}}}


class NativeAccountingBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-accounting-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "source.jsonl"

    def run_phase(self, rows, tail=b""):
        self.path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows) + tail)
        cell = self.root / "phase"
        cell.mkdir()
        # This fixture exercises accounting without importing historical task context.
        registration = {"purpose": "automatic_selection_generation_only", "shared_request": "continuation", "pins": {},
                        "origin": str(self.root), "initial_manifest": {}}
        return phase(FinishedServer(), {"thread": {"id": "t1", "path": str(self.path)}},
                     registration, cell, None, time.monotonic() + 2)

    def test_complete_json_at_eof_is_not_silently_lost(self):
        row = receipt()
        self.path.write_bytes(json.dumps(row).encode())
        self.assertEqual([row], records(self.path))

    def test_completed_rpc_with_partial_durable_tail_is_not_complete_usage(self):
        result = self.run_phase(finished_rows(), b'{"type":"token_usage_record"')
        self.assertFalse(result["usage_complete"])

    def test_missing_final_receipt_is_detected_by_native_cumulative_usage(self):
        rows = finished_rows()
        del rows[1]
        result = self.run_phase(rows)
        self.assertFalse(result["usage_complete"])

    def test_missing_durable_completion_is_not_complete_usage(self):
        result = self.run_phase(finished_rows()[:-1])
        self.assertFalse(result["usage_complete"])

    def test_unrelated_turn_receipt_does_not_prove_current_turn_usage(self):
        rows = finished_rows()
        for row in rows[:2]:
            row["payload"]["turn_id"] = "different_turn"
        result = self.run_phase(rows)
        self.assertFalse(result["usage_complete"])

    def test_call_timeout_has_the_declared_exception_type(self):
        rpc = NativeRPC.__new__(NativeRPC)
        rpc.counter, rpc.queue, rpc.pending = 0, queue.Queue(), []
        rpc.send = lambda value: None
        with self.assertRaises(TimeoutError):
            rpc.call("offline/request", {}, timeout=.005)

    def test_complete_phase_preserves_and_accounts_for_the_same_bytes(self):
        result = self.run_phase(finished_rows())
        self.assertTrue(result["usage_complete"])
        self.assertEqual(self.path.read_bytes(), (self.root / "phase/rollout.jsonl").read_bytes())
        self.assertEqual(24, result["receipts"]["all_usage"]["total_tokens"])
        self.assertEqual(result["rollout_sha256"], result["usage_completion_evidence"]["rollout_sha256"])

    def test_missing_middle_receipt_cannot_pass_cumulative_chain(self):
        rows = finished_rows()[1:]
        self.assertFalse(self.run_phase(rows)["usage_complete"])

    def test_complete_compaction_uses_its_embedded_receipt_not_reset_token_count(self):
        row = receipt()
        rows = [row, {"type": "compacted", "payload": {
            "compaction_response_id": "r1", "latest_token_usage_record": copy.deepcopy(row["payload"])}},
            finished_rows()[-1]]
        snapshot = parse_rollout(b"\n".join(json.dumps(r).encode() for r in rows))
        proof = completion_evidence(snapshot, usage(snapshot.rows, "t1"), turn_id="turn1", compact=True)
        self.assertTrue(proof["complete"])
        rows[1]["payload"]["latest_token_usage_record"]["usage"]["total_tokens"] = 999
        snapshot = parse_rollout(b"\n".join(json.dumps(r).encode() for r in rows))
        self.assertFalse(completion_evidence(snapshot, usage(snapshot.rows, "t1"),
                                            turn_id="turn1", compact=True)["complete"])

    def test_strict_physical_lines_keep_valid_unicode_and_exact_archive(self):
        row = {"type": "response_item", "payload": {"text": "valid \ufffd and \u2028"}}
        raw = b'\n' + json.dumps(row, ensure_ascii=False).encode("utf-8") + b'\n' + json.dumps(receipt()).encode()
        self.path.write_bytes(raw)
        archive = self.root / "archive.jsonl"
        snapshot = capture_rollout(self.path, archive=archive)
        self.assertEqual(raw, archive.read_bytes())
        self.assertEqual([2, 3], snapshot.line_numbers)
        self.assertEqual(row, snapshot.rows[0])
        self.assertTrue(snapshot.metadata["parse_complete"])
        self.assertEqual(3, usage(snapshot.rows, "t1", line_numbers=snapshot.line_numbers)
                         ["response_receipts"][0]["rollout_line"])

    def test_malformed_interior_is_not_hidden_as_an_active_tail(self):
        with self.assertRaisesRegex(ValueError, "line=1"):
            parse_rollout(b'{"type":"response_item","payload":"\xff"}\n')
        snapshot = parse_rollout(b'{"type":"response_item","payload":"\xff')
        self.assertFalse(snapshot.metadata["parse_complete"])


if __name__ == "__main__":
    unittest.main()
