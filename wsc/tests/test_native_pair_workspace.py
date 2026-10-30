"""Exercise file restoration while a real child retains the workspace cwd."""
from pathlib import Path
import shutil
import py_compile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_evidence import manifest
from native_pair_workspace import preserve_arm


class WorkspaceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.area, self.frozen = root / "trial", root / "frozen"
        self.frozen.mkdir()
        (self.frozen / "reader.py").write_bytes(b"before\n")
        (self.frozen / "protected.py").write_bytes(b"protected\n")
        self.initial = manifest(self.frozen)
        self.work = self.area / "workspace"
        shutil.copytree(self.frozen, self.work)
        (self.work / "reader.py").write_bytes(b"after\n")
        (self.work / "report.json").write_bytes(b"{}\n")

    def test_snapshot_restore_with_live_child_cwd_and_preserved_outputs(self):
        child = subprocess.Popen([sys.executable, "-u", "-c", "print('ready',flush=True);input()"],
            cwd=self.work, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            if sys.platform == "win32":
                with self.assertRaises(PermissionError):
                    self.work.rename(self.area / "old-rename-strategy")
            before = manifest(self.work)
            receipt = preserve_arm(self.area, "B", self.frozen, self.initial, restore_initial=True)
            self.assertEqual(manifest(self.area / "B/final-workspace"), before)
            self.assertEqual(manifest(self.work), self.initial)
            self.assertFalse(receipt["cwd_directory_moved"])
            self.assertIsNone(child.poll())
            (self.work / "reader.py").write_bytes(b"C result\n")
            c_final = manifest(self.work)
            preserve_arm(self.area, "C", self.frozen, self.initial, restore_initial=False)
            self.assertEqual(manifest(self.area / "C/final-workspace"), c_final)
            self.assertEqual(manifest(self.work), c_final)
            self.assertEqual(manifest(self.frozen), self.initial)
        finally:
            child.communicate("\n", timeout=5)

    def test_failed_snapshot_does_not_reset_source(self):
        before = manifest(self.work)
        with patch("native_pair_workspace.shutil.copytree", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                preserve_arm(self.area, "B", self.frozen, self.initial, restore_initial=True)
        self.assertEqual(manifest(self.work), before)

    def test_rehearsal_leaves_final_archive_namespace_available(self):
        preserve_arm(self.area, "B", self.frozen, self.initial, restore_initial=True, rehearsal=True)
        self.assertEqual(manifest(self.work), self.initial)
        self.assertTrue((self.area / "B/rehearsal-workspace").is_dir())
        self.assertFalse((self.area / "B/final-workspace").exists())
        (self.work / "reader.py").write_bytes(b"actual result\n")
        final = manifest(self.work)
        preserve_arm(self.area, "B", self.frozen, self.initial, restore_initial=True)
        self.assertEqual(manifest(self.area / "B/final-workspace"), final)
        self.assertEqual(manifest(self.work), self.initial)

    def test_restore_clears_prior_arm_compiled_code(self):
        cache = Path(py_compile.compile(str(self.work / "reader.py"), doraise=True))
        self.assertTrue(cache.exists())
        receipt = preserve_arm(self.area, "B", self.frozen, self.initial, restore_initial=True)
        self.assertFalse(cache.exists())
        self.assertIn(cache.relative_to(self.work).as_posix(), receipt["removed_runtime_caches"])
        self.assertEqual(manifest(self.work), self.initial)

    def test_escape_in_registered_manifest_is_rejected_before_writes(self):
        before = manifest(self.work)
        with self.assertRaisesRegex(ValueError, "unsafe_workspace_relative_path"):
            preserve_arm(self.area, "B", self.frozen, {"../outside": "hash"}, restore_initial=True)
        self.assertEqual(manifest(self.work), before)
        self.assertFalse((self.area / "B").exists())

    def test_existing_archive_is_never_overwritten(self):
        archive = self.area / "B/final-workspace"
        archive.mkdir(parents=True)
        (archive / "evidence").write_bytes(b"preserved")
        before = manifest(self.work)
        with self.assertRaisesRegex(ValueError, "existing_archive"):
            preserve_arm(self.area, "B", self.frozen, self.initial, restore_initial=True)
        self.assertEqual(manifest(self.work), before)
        self.assertEqual((archive / "evidence").read_bytes(), b"preserved")


if __name__ == "__main__":
    unittest.main()
