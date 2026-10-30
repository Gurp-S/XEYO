"""The generation runner uses the same host gate before its first paid call."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]
from native_group_admission import NativeGroupAdmission
import run_frontier_generation as runner


class GenerationAdmissionTests(unittest.TestCase):
    def observations(self):
        return {name: {"thread_id": name, "rollout_path": name, "host": {"skills": ["local"]},
            "controls_sha256": "same", "prefix_sha256": name, "response_count": 0}
                for name in ("full", "frontier")}

    def test_plugin_bootstrap_difference_blocks_both_paid_callbacks(self):
        observed = self.observations()
        observed["frontier"]["host"]["skills"].append("plugins")
        calls = []
        with self.assertRaisesRegex(ValueError, "host_drift_before_inference"):
            gate = NativeGroupAdmission(observed, members=("full", "frontier"))
            gate.execute("full", observed, lambda: calls.append("paid"))
        self.assertEqual([], calls)

    def test_new_runner_cannot_enter_generation_when_admission_fails(self):
        reg = {"workspace": "unused", "executable": "unused", "order": ["full", "frontier"]}
        with patch.object(runner, "read", return_value=reg), patch.object(runner, "save"), \
             patch.object(runner, "verify_pins"), patch.object(runner, "NativeRPC"), \
             patch.object(runner, "initialize"), patch.object(runner, "archive_threads"), \
             patch.object(runner, "admit", side_effect=ValueError("native_group_host_drift_before_inference")), \
             patch.object(runner, "phase") as phase:
            with self.assertRaisesRegex(ValueError, "host_drift_before_inference"):
                runner.run(Path("unused"))
            phase.assert_not_called()

    def test_two_member_group_keeps_one_attempt_and_rechecks_retained_identity(self):
        observed = self.observations()
        gate = NativeGroupAdmission(observed, members=observed)
        gate.execute("full", observed, lambda: None)
        observed["full"]["response_count"] = 1
        drifted = deepcopy(observed)
        drifted["frontier"]["thread_id"] = "replacement"
        with self.assertRaisesRegex(ValueError, "retained_thread_drift"):
            gate.execute("frontier", drifted, lambda: self.fail("called"))
        gate.execute("frontier", observed, lambda: None)
        with self.assertRaisesRegex(ValueError, "repeated"):
            gate.execute("full", observed, lambda: self.fail("retried"))


if __name__ == "__main__":
    unittest.main()
