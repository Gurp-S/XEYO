from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_evidence import FIELDS
from native_turn_accounting import account_turn, admit_resumed_turn


def amount(n):
    return {**dict.fromkeys(FIELDS, 0), "input_tokens": 10*n, "output_tokens": 2*n, "total_tokens": 12*n}


def event(kind, **values):
    return {"type": "event_msg", "payload": {"type": kind, **values}}


def paid(rid, turn, cumulative, thread):
    return {"type": "token_usage_record", "payload": {"thread_id": "thread", "turn_id": turn,
        "response_id": rid, "usage": amount(1), "turn_token_usage": amount(cumulative),
        "thread_token_usage": amount(thread)}}


def count(total, last=1):
    return event("token_count", info={"total_token_usage": amount(total), "last_token_usage": amount(last)})


def raw(rows):
    return b"".join(json.dumps(r).encode() + b"\n" for r in rows)


class NativeTurnAccountingTests(unittest.TestCase):
    def setUp(self):
        self.before = [{"type": "session_meta", "payload": {"id": "thread"}},
            event("task_started", turn_id="old"), paid("old-response", "old", 1, 10),
            count(8), event("task_complete", turn_id="old")]
        compaction = paid("compact", "new", 2, 12)
        self.delta = [event("task_started", turn_id="new"), paid("first", "new", 1, 11), count(9),
            compaction, {"type": "compacted", "payload": {"compaction_response_id": "compact",
                "latest_token_usage_record": deepcopy(compaction["payload"])}},
            count(9, 0), paid("last", "new", 3, 13), count(10), event("task_complete", turn_id="new")]

    def proof(self, delta=None):
        return account_turn(raw(self.before), raw(self.before + (self.delta if delta is None else delta)),
                            thread_id="thread", turn_id="new")

    def test_resumed_turn_counts_compaction_and_excludes_inherited_counter(self):
        result = self.proof()
        self.assertTrue(result["complete"], result["reasons"])
        self.assertEqual(36, result["complete_usage"]["total_tokens"])
        self.assertEqual(12, result["known_compaction_usage"]["total_tokens"])
        self.assertEqual(24, result["known_normal_usage"]["total_tokens"])
        self.assertEqual(120, result["inherited_thread_counter"]["total_tokens"])
        self.assertEqual(["first", "compact", "last"], [r["response_id"] for r in result["receipts"]["response_receipts"]])

    def test_fresh_thread_and_explicit_compaction_are_supported(self):
        self.before = self.before[:1]
        one = paid("first", "new", 1, 1)
        for middle in [[count(1)], [{"type": "compacted", "payload": {
                "compaction_response_id": "first", "latest_token_usage_record": deepcopy(one["payload"])}}]]:
            result = self.proof([event("task_started", turn_id="new"), one, *middle,
                                 event("task_complete", turn_id="new")])
            self.assertTrue(result["complete"], result["reasons"])

    def test_missing_middle_or_final_receipt_never_becomes_complete(self):
        for index in (3, 6):
            changed = deepcopy(self.delta)
            del changed[index]
            result = self.proof(changed)
            self.assertFalse(result["complete"])
            self.assertIsNone(result["complete_usage"])
            self.assertEqual(24, result["known_usage"]["total_tokens"])

    def test_equal_duplicate_is_counted_once_and_conflicting_duplicate_rejected(self):
        rows = deepcopy(self.delta)
        rows.insert(2, deepcopy(rows[1]))
        self.assertEqual(3, self.proof(rows)["receipts"]["response_count"])
        self.assertEqual(["first"], self.proof(rows)["duplicate_response_ids"])
        self.assertTrue(self.proof(rows)["complete"])
        rows[2]["payload"]["thread_token_usage"] = amount(99)
        self.assertIn("turn_duplicate_receipt_conflict", self.proof(rows)["reasons"])

    def test_historical_response_identity_cannot_be_rebilled(self):
        rows = deepcopy(self.delta)
        rows[1]["payload"]["response_id"] = "old-response"
        result = self.proof(rows)
        self.assertIn("turn_response_reused_from_history", result["reasons"])
        self.assertEqual(24, result["known_usage"]["total_tokens"])

    def test_interruption_retains_known_cost_without_inventing_complete_total(self):
        result = self.proof(self.delta[:-1] + [event("turn_aborted", turn_id="new")])
        self.assertFalse(result["complete"])
        self.assertIsNone(result["complete_usage"])
        self.assertEqual(36, result["known_usage"]["total_tokens"])

    def test_unfinished_physical_tail_invalidates_completeness(self):
        result = account_turn(raw(self.before), raw(self.before + self.delta) + b'{"type":',
                              thread_id="thread", turn_id="new")
        self.assertIn("turn_rollout_incomplete", result["reasons"])
        self.assertEqual(36, result["known_usage"]["total_tokens"])

    def test_changed_historical_bytes_cannot_redefine_new_phase(self):
        changed = raw(self.before + self.delta).replace(b'"old"', b'"xyz"', 1)
        result = account_turn(raw(self.before), changed, thread_id="thread", turn_id="new")
        self.assertIn("turn_source_prefix_changed", result["reasons"])
        self.assertIsNone(result["complete_usage"])

    def test_compaction_receipt_substitution_and_reuse_rejected(self):
        rows = deepcopy(self.delta)
        rows[4]["payload"]["latest_token_usage_record"]["usage"] = amount(2)
        self.assertIn("turn_compaction_receipt_unbound", self.proof(rows)["reasons"])
        rows = deepcopy(self.delta)
        rows.insert(5, deepcopy(rows[4]))
        self.assertIn("turn_compaction_receipt_reused", self.proof(rows)["reasons"])

    def test_next_turn_and_already_started_turn_are_not_the_registered_interval(self):
        rows = self.delta + [event("task_started", turn_id="next"), paid("next-response", "next", 1, 14)]
        self.assertIn("turn_start_missing_or_ambiguous", self.proof(rows)["reasons"])
        result = account_turn(raw(self.before + self.delta[:2]), raw(self.before + self.delta),
                              thread_id="thread", turn_id="new")
        self.assertIn("turn_already_started_at_boundary", result["reasons"])

    def test_first_available_window_with_inherited_unseen_cost_is_not_fresh(self):
        self.before = self.before[:1]
        rows = [event("task_started", turn_id="new"), paid("first", "new", 1, 100), count(99),
                event("task_complete", turn_id="new")]
        result = self.proof(rows)
        self.assertIn("turn_thread_counter_gap", result["reasons"])
        self.assertIsNone(result["complete_usage"])

    def test_invalid_receipt_is_unknown_not_zero_or_a_crash(self):
        rows = deepcopy(self.delta)
        rows[1]["payload"]["response_id"] = []
        self.assertIn("turn_receipt_invalid", self.proof(rows)["reasons"])

    def test_live_resumed_admission_needs_prior_counter_and_matching_thread(self):
        self.assertTrue(admit_resumed_turn(raw(self.before), thread_id="thread").metadata["parse_complete"])
        for rows, tid in [(self.before[:1], "thread"), (self.before, "other"),
                          ([r for r in self.before if r.get("payload", {}).get("type") != "token_count"], "thread")]:
            with self.subTest(thread=tid), self.assertRaises(ValueError):
                admit_resumed_turn(raw(rows), thread_id=tid)


class NativeTurnEntryTests(unittest.TestCase):
    def test_shared_phase_does_not_charge_or_cap_using_old_responses(self):
        from run_native_pair import phase
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frozen-workspace").mkdir()
            cell = root / "phase"
            cell.mkdir()
            before = [{"type": "session_meta", "payload": {"id": "thread"}},
                      event("task_started", turn_id="old")]
            before += [paid("old-"+str(i), "old", i, i) for i in range(1, 13)]
            before += [count(12), event("task_complete", turn_id="old")]
            after = before + [event("task_started", turn_id="new"), paid("new-response", "new", 1, 13),
                              count(13), event("task_complete", turn_id="new")]
            path = root / "source.jsonl"
            path.write_bytes(raw(before))

            class Server:
                def __init__(self):
                    self.events = iter([{"method": "thread/tokenUsage/updated", "params": {"threadId": "thread"}},
                        {"method": "turn/completed", "params": {"threadId": "thread", "turn": {"id": "new", "status": "completed"}}}])

                def call(self, method, params):
                    if method != "turn/start":
                        raise AssertionError("unexpected interrupt")
                    path.write_bytes(raw(after))
                    return {"turn": {"id": "new"}}

                def event(self, **kwargs):
                    return next(self.events)

            result = phase(Server(), {"thread": {"id": "thread", "path": str(path)}},
                {"purpose": "automatic_selection_generation_only", "accounting_scope": "append_only_turn",
                 "shared_request": "fixture", "origin": str(root), "initial_manifest": {}, "pins": {}},
                cell, None, time.monotonic() + 2)
            self.assertTrue(result["usage_complete"], result)
            self.assertEqual(1, result["receipts"]["response_count"])
            self.assertEqual(12, result["receipts"]["all_usage"]["total_tokens"])
            self.assertIsNone(result["failure"])
            self.assertTrue((cell / "accounting-start.json").exists())
