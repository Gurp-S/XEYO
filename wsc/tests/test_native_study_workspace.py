"""Stable owned cwd survives qualification snapshots without touching other roots."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_evidence import manifest, read
from native_study_workspace import create, validate, RECEIPT
from native_pair_workspace import preserve_arm


class NativeStudyWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wsc-stable-study-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.frozen = self.root / "frozen"
        self.frozen.mkdir()
        (self.frozen / "source.py").write_bytes(b"initial\n")
        self.initial = manifest(self.frozen)
        self.owner = self.root / "study"
        create(self.owner, self.frozen)
        self.work = self.owner / "workspace"

    def test_qualification_archives_result_then_restores_same_directory_for_comparison(self):
        qualification = self.owner / "qualification"
        qualification.mkdir()
        self.assertEqual(self.work, validate(qualification, self.work, self.frozen, self.initial, require_initial=True)[0])
        (self.work / "source.py").write_bytes(b"qualified\n")
        (self.work / "new.txt").write_bytes(b"owned new output")
        result = preserve_arm(qualification, "C", self.frozen, self.initial,
                              restore_initial=True, workspace=self.work)
        self.assertFalse(result["cwd_directory_moved"])
        self.assertEqual(b"qualified\n", (qualification / "C/final-workspace/source.py").read_bytes())
        self.assertEqual(self.initial, manifest(self.work))
        self.assertEqual(self.initial, manifest(self.frozen))
        validate(self.owner / "comparison", self.work, self.frozen, self.initial, require_initial=True)

    def test_unowned_workspace_or_other_study_area_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        for area, work in ((outside, self.work), (self.owner / "qualification", outside)):
            with self.subTest(area=area, work=work), self.assertRaises(ValueError):
                preserve_arm(area, "C", self.frozen, self.initial, restore_initial=True, workspace=work)
        self.assertEqual(self.initial, manifest(self.work))

    def test_changed_receipt_or_initial_bytes_cannot_be_reused_as_qualified_start(self):
        (self.work / "source.py").write_bytes(b"changed\n")
        with self.assertRaisesRegex(ValueError, "study_workspace_not_at_start"):
            validate(self.owner / "comparison", self.work, self.frozen, self.initial, require_initial=True)
        receipt = read(self.owner / RECEIPT)
        receipt["frozen"] = str(self.root / "other")
        (self.owner / RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "study_ownership_mismatch"):
            validate(self.owner / "comparison", self.work, self.frozen, self.initial)

    def test_existing_owner_is_never_reinitialized(self):
        (self.work / "source.py").write_bytes(b"existing work\n")
        with self.assertRaisesRegex(ValueError, "study_owner_already_exists"):
            create(self.owner, self.frozen)
        self.assertEqual(b"existing work\n", (self.work / "source.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
