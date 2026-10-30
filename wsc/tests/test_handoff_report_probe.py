import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from run_handoff_report_probe import preflight
from native_execution_binding import report_execution_item
from native_evidence import digest, file_hash, manifest


class ReportAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "frozen-workspace").mkdir()
        self.work = self.root / "workspace"
        self.work.mkdir()
        (self.work / "source.py").write_text("old\n")
        self.evidence = self.root / "evidence.txt"
        self.evidence.write_bytes(b"exact observation")
        index = self.root / "index.json"
        index.write_text("{}")
        self.package = {"items": [{"role": "assistant", "text": "unchanged imperfect interpretation"}],
            "evidence": {"source": {"file_path": str(self.evidence), "sha256": file_hash(self.evidence)}},
            "source_index": str(index), "source_index_sha256": digest({}),
            "understanding_index": str(index), "understanding_index_sha256": digest({})}
        self.package["package_digest"] = digest(self.package)
        self.path = self.root / "package.json"
        self.path.write_text(json.dumps(self.package))
        self.reg = {"pins": {str(self.path): file_hash(self.path)}, "origin": str(self.root),
            "initial_manifest": {}, "workspace": str(self.work), "task_manifest": manifest(self.work),
            "package": str(self.path), "items_sha256": digest(self.package["items"])}
        self.reg["execution_fact"] = report_execution_item(self.work, self.reg["task_manifest"])

    def test_exact_items_pass_without_claiming_semantics(self):
        self.assertEqual(preflight(self.reg), self.package["items"] + [self.reg["execution_fact"]])

    def test_missing_current_execution_fact_rejected(self):
        self.reg.pop("execution_fact")
        with self.assertRaisesRegex(ValueError, "report_execution_fact_missing_or_changed"):
            preflight(self.reg)

    def test_task_drift_rejected(self):
        (self.work / "source.py").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "report_task_workspace_changed"):
            preflight(self.reg)

    def test_cold_evidence_drift_rejected(self):
        self.evidence.write_bytes(b"different observation")
        with self.assertRaisesRegex(ValueError, "report_export_changed"):
            preflight(self.reg)

    def test_modified_handoff_rejected(self):
        self.path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "registered_input_changed"):
            preflight(self.reg)
