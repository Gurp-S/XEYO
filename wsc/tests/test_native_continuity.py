from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_continuity_checks import aggregate
from native_evidence import FIELDS, read, save
import run_native_continuity as runner


def outcome(rid, amount=2, complete=True):
    usage = dict.fromkeys(FIELDS, 0)
    usage.update(input_tokens=amount, total_tokens=amount)
    return {"completed": True, "failure": None, "usage_complete": complete,
            "receipts": {"response_receipts": [{"response_id": rid, "usage": usage}]}}


class CostTests(unittest.TestCase):
    def test_only_unique_stage_costs_are_added(self):
        result = aggregate([outcome("a", 2), outcome("b", 5)])
        self.assertEqual(7, result["complete_usage"]["total_tokens"])
        self.assertEqual(2, result["response_count"])
        self.assertIsNone(result["cash"])

    def test_accidental_full_history_second_stage_cannot_double_bill(self):
        with self.assertRaisesRegex(ValueError, "billed_twice"):
            aggregate([outcome("a"), outcome("a")])

    def test_incomplete_stage_retains_known_cost_without_claiming_total(self):
        result = aggregate([outcome("a"), outcome("b", complete=False)])
        self.assertEqual(4, result["known_usage"]["total_tokens"])
        self.assertIsNone(result["complete_usage"])


class DriverTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.area = Path(tmp.name)
        self.workspace = self.area / "workspace"
        self.workspace.mkdir()
        self.initial = {"AGENTS.md": "rules"}
        save(self.area / "registration.json", {"workspace": str(self.workspace), "initial_manifest": self.initial,
             "executable": "unused", "grader": "unused"})
        self.package = {"stages": [{"id": name, "message": name, "acceptance_class": scope}
            for name, scope in [("revision", "RevisionContractTests"), ("explicit_identity", "all"), ("handoff", None)]]}
        self.opened = {"model": runner.MODEL, "reasoningEffort": "max", "sandbox": {"type": "workspaceWrite"},
                       "approvalPolicy": "never", "thread": {"id": "thread", "path": "unused"}}
        self.server = Mock()
        self.server.call.side_effect = [{}, {}, self.opened]
        self.receipt = {"source_manifest_sha256": "actual-source", "scope": "all", "tests": 9,
                        "passed": True, "grader_sha256": "grader"}

    def execute(self, outcomes, *, passed=True):
        receipt = {**self.receipt, "passed": passed}
        cost = aggregate(outcomes)
        final = {"native": {"receipts": {"all_usage": cost["known_usage"],
                 "response_receipts": [r for o in outcomes for r in o["receipts"]["response_receipts"]]}}}
        with patch.object(runner, "preflight", return_value=self.package), \
             patch.object(runner, "manifest", return_value=self.initial), \
             patch.object(runner, "NativeRPC") as rpc, \
             patch.object(runner, "initialize", return_value={}), \
             patch.object(runner, "import_items") as inject, \
             patch.object(runner, "observe", return_value={"response_count": 0}), \
             patch.object(runner, "archive_workspace", return_value={"manifest": self.initial}), \
             patch.object(runner, "grade", return_value=receipt) as grader, \
             patch.object(runner, "archive_threads", return_value=final), \
             patch.object(runner, "phase", side_effect=outcomes) as phase:
            rpc.return_value.__enter__.return_value = self.server
            runner.run(self.area)
        return read(self.area / "result.json"), phase, grader, inject

    def test_three_stages_use_same_thread_and_incremental_accounting(self):
        result, phase, grader, inject = self.execute([outcome("a"), outcome("b"), outcome("c")])
        self.assertEqual("executed_semantic_review_pending", result["status"])
        self.assertEqual(3, phase.call_count)
        self.assertEqual(2, grader.call_count)
        self.assertEqual(["fresh_single_turn", "append_only_turn", "append_only_turn"],
                         [c.args[2]["accounting_scope"] for c in phase.call_args_list])
        self.assertTrue(all(c.args[1] is self.opened for c in phase.call_args_list))
        self.assertEqual("actual-source", __import__("json").loads(inject.call_args_list[1].args[2][0]
                         ["content"][0]["text"])["prior_acceptance"]["source_manifest_sha256"])

    def test_failed_acceptance_stops_later_paid_turns(self):
        result, phase, grader, _ = self.execute([outcome("a")], passed=False)
        self.assertEqual(1, phase.call_count)
        self.assertEqual("stopped", result["status"])
        self.assertIn("acceptance_failed", result["error"])

    def test_unknown_usage_stops_before_grading_or_next_turn(self):
        result, phase, grader, _ = self.execute([outcome("a", complete=False)])
        grader.assert_not_called()
        self.assertEqual(1, phase.call_count)
        self.assertIsNone(result["usage"]["complete_usage"])

    def test_prior_started_attempt_cannot_be_reentered(self):
        save(self.area / "started.json", {"status": "failed"})
        with patch.object(runner, "preflight", return_value=self.package), \
             patch.object(runner, "manifest", return_value=self.initial), \
             patch.object(runner, "NativeRPC") as rpc, self.assertRaises(FileExistsError):
            runner.run(self.area)
        rpc.assert_not_called()
