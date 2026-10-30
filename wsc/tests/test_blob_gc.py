import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wsc import blob_gc
from wsc.tool_results import ResultStore


class BlobGcChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ResultStore(Path(self.temp.name) / "results", session="session")
        self.store.capture("call-1", "referenced text", {})
        self.kept = sorted(Path(self.store.objects).glob("*.txt"))[0].name
        self.stray = Path(self.store.objects) / ("0" * 64 + ".txt")
        self.stray.write_text("orphan", encoding="utf-8")

    def test_dry_run_reports_without_touching_anything(self):
        report = blob_gc.collect(self.store)
        self.assertEqual([self.stray.name], report["orphans"])
        self.assertEqual([], report["removed"])
        self.assertTrue(self.stray.exists())

    def test_referenced_blob_is_never_collected(self):
        report = blob_gc.collect(self.store, dry_run=False)
        self.assertEqual([self.stray.name], report["removed"])
        self.assertTrue((Path(self.store.objects) / self.kept).exists())
        self.assertFalse(self.stray.exists())

    def test_caller_declared_hash_protects_a_staged_blob(self):
        report = blob_gc.collect(self.store, keep_hashes={self.stray.stem}, dry_run=False)
        self.assertEqual([], report["removed"])
        self.assertTrue(self.stray.exists())

    def test_open_intent_hashes_are_resolved_from_its_call_id(self):
        self.assertEqual({Path(self.kept).stem},
                         blob_gc.live_hashes(self.store, call_ids={"call-1"}))

    def test_open_intent_protects_its_blob_during_collection(self):
        keep = blob_gc.live_hashes(self.store, call_ids={"call-1"})
        blob_gc.collect(self.store, keep_hashes=keep, dry_run=False)
        self.assertTrue((Path(self.store.objects) / self.kept).exists())
        self.assertFalse(self.stray.exists())

    def test_second_run_is_idempotent(self):
        blob_gc.collect(self.store, dry_run=False)
        self.assertEqual([], blob_gc.collect(self.store)["orphans"])


if __name__ == "__main__":
    unittest.main()
