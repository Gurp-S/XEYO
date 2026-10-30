"""A host mismatch must stop before even the first paid compaction call."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_pair_admission import PairAdmission


class PairAdmissionTests(unittest.TestCase):
    def observations(self):
        return {name: {"thread_id": name, "rollout_path": name + ".jsonl", "host": {"skills": ["a", "b"]},
            "controls_sha256": "original", "prefix_sha256": name + "-prefix", "response_count": 0}
            for name in ("compaction", "B", "C")}

    def test_late_arm_host_drift_prevents_first_paid_call(self):
        observed = self.observations()
        observed["C"]["host"]["skills"].pop()
        calls = []
        with self.assertRaisesRegex(ValueError, "host_drift_before_inference"):
            gate = PairAdmission(observed)
            gate.execute("compaction", observed, lambda: calls.append("paid"))
        self.assertEqual(calls, [])

    def test_same_native_configuration_allows_each_phase_once(self):
        observed = self.observations()
        gate = PairAdmission(observed)
        calls = []
        for name in ("compaction", "B", "C"):
            gate.execute(name, observed, lambda: calls.append(name))
            observed[name]["response_count"] = 1
        self.assertEqual(calls, ["compaction", "B", "C"])
        with self.assertRaisesRegex(ValueError, "repeated"):
            gate.execute("C", observed, lambda: calls.append("retry"))

    def test_retained_thread_change_is_checked_again_before_spending(self):
        observed = self.observations()
        gate = PairAdmission(observed)
        observed["C"]["host"]["skills"].append("changed")
        calls = []
        with self.assertRaisesRegex(ValueError, "retained_thread_drift"):
            gate.execute("compaction", observed, lambda: calls.append("paid"))
        self.assertEqual(calls, [])

    def test_failed_callback_cannot_be_retried(self):
        observed = self.observations()
        gate = PairAdmission(observed)
        def lost():
            raise TimeoutError("unknown outcome")
        with self.assertRaises(TimeoutError):
            gate.execute("compaction", observed, lost)
        with self.assertRaisesRegex(ValueError, "repeated"):
            gate.execute("compaction", observed, lost)

    def test_partial_or_preused_pair_rejected(self):
        for mutation in ("missing", "spent", "identity", "control"):
            with self.subTest(mutation=mutation):
                observed = self.observations()
                if mutation == "missing": del observed["C"]
                if mutation == "spent": observed["C"]["response_count"] = 1
                if mutation == "identity": observed["C"]["thread_id"] = "B"
                if mutation == "control": observed["C"]["controls_sha256"] = "changed"
                with self.assertRaises(ValueError):
                    PairAdmission(observed)

    def test_admission_keeps_snapshot_immutable(self):
        observed = self.observations()
        original = deepcopy(observed)
        gate = PairAdmission(observed)
        observed["B"]["prefix_sha256"] = "rewritten"
        self.assertEqual(gate.observations, original)


if __name__ == "__main__":
    unittest.main()
