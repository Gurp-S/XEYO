"""Comparison cannot spend before a matching, intact C completion receipt."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_evidence import digest, file_hash, manifest, save
from native_c_qualification import fingerprint, require_qualification
import run_admitted_pair


class QualificationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reg = {"purpose": "comparison", "model": "model", "effort": "max", "settings": [],
            "dynamic_tools": [], "pins": {"source": "hash"}, "shared_request": "task",
            "raw_source_items_sha256": "source", "admission_warmup_threads": 1,
            "orchestration": "test", "initial_manifest": {"reader": "old"},
            "caps": {"responses_per_arm_including_compaction": 10, "wall_seconds_per_arm": 480,
                     "model_requested_checks_per_arm": 3, "native_compaction_calls": 1}}

    def proof(self):
        names = ("registration.json", "result.json", "native-cwd-rehearsal.json", "C/artifact-outcome.json",
                 "C/workspace-lifecycle.json", "C/continuation/import-audit.json",
                 "native-rollout-archive/C.jsonl", "semantic-review.json")
        for name in names:
            save(self.root / name, {"test_fixture": name})
        archive = self.root / "C/final-workspace"
        archive.mkdir()
        (archive / "reader").write_bytes(b"fixed")
        receipt = {"status": "C_ready_for_registered_comparison", "fingerprint": fingerprint(self.reg),
            "evidence_sha256": {name: file_hash(self.root / name) for name in names},
            "final_manifest_sha256": digest(manifest(archive))}
        save(self.root / "qualification.json", receipt)
        self.reg["qualification_receipt"] = {"path": str(self.root / "qualification.json"),
                                             "sha256": file_hash(self.root / "qualification.json")}

    def test_missing_qualification_stops_before_starting_native_server(self):
        save(self.root / "registration.json", self.reg)
        with patch.object(run_admitted_pair.driver, "open_server") as server:
            with self.assertRaisesRegex(ValueError, "qualification_required"):
                run_admitted_pair.run(self.root)
        server.assert_not_called()

    def test_successful_receipt_is_invalidated_by_any_bound_drift(self):
        self.proof()
        require_qualification(self.reg)
        for field in ("model", "shared_request", "orchestration", "raw_source_items_sha256"):
            with self.subTest(field=field):
                changed = deepcopy(self.reg)
                changed[field] = "changed"
                with self.assertRaisesRegex(ValueError, "configuration_drift"):
                    require_qualification(changed)
        artifact = self.root / "C/final-workspace/reader"
        artifact.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "artifact_changed"):
            require_qualification(self.reg)
        artifact.write_bytes(b"fixed")
        (self.root / "semantic-review.json").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "evidence_changed"):
            require_qualification(self.reg)

    def test_qualification_mode_cannot_include_B_or_compaction(self):
        self.reg.update(purpose="C_qualification", order=["C"])
        with self.assertRaisesRegex(ValueError, "must_not_run_B"):
            require_qualification(self.reg)
        self.reg["caps"]["native_compaction_calls"] = 0
        require_qualification(self.reg)
        self.reg["order"] = ["B", "C"]
        with self.assertRaisesRegex(ValueError, "must_not_run_B"):
            require_qualification(self.reg)


if __name__ == "__main__":
    unittest.main()
