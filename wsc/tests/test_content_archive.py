"""Shared bytes never merge occurrence identity or remove the full cold archive."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Selection, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.content_archive import publish_object
from wsc.publication import check_evidence
from test_contracts import DurableTestHost, message


class ContentArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wsc-content-archive-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.denied = set()
        self.core = WSC(Store(self.root / "state.db", session_id="session", workspace=str(self.root)),
                        access=lambda session, source, action: (source, action) not in self.denied)
        self.adapter = CodexCheckpointAdapter()
        self.items = [message("user", "task"), message("assistant", "same observation"),
                      message("assistant", "same observation"), {"type": "reasoning", "encrypted_content": "opaque"}]
        self.ids = self.core.ingest(self.adapter.import_items(self.items, thread_id="source",
            observed_at=["time-1", "time-2", "time-3", "time-4"]))
        self.archive = self.root / "cold"

    def stage(self):
        view = self.core.prepare(self.core.capture(), Selection(), producer="offline-test")
        return self.core.stage(view, directory=self.root / "exports", adapter=self.adapter,
                               archive_directory=self.archive)

    def test_republication_reuses_all_cold_bytes_and_preserves_occurrences(self):
        first = self.stage()
        package = self.core.package(first)
        self.assertEqual(set(self.ids), set(package["evidence"]))
        self.assertEqual(package["evidence"][self.ids[1]]["file_path"],
                         package["evidence"][self.ids[2]]["file_path"])
        self.assertNotEqual(package["evidence"][self.ids[1]]["observed_at"],
                            package["evidence"][self.ids[2]]["observed_at"])
        files = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.archive.rglob("*") if p.is_file()}
        self.core.discard(first)
        second = self.stage()
        self.assertEqual(package["evidence"], self.core.package(second)["evidence"])
        self.assertEqual(files, {str(p): (p.stat().st_mtime_ns, p.read_bytes())
                                 for p in self.archive.rglob("*") if p.is_file()})
        check_evidence(self.core, self.core.package(second))

    def test_incremental_source_keeps_old_index_and_adds_only_new_objects(self):
        first = self.stage()
        before = self.core.package(first)
        old_files = set(self.archive.rglob("*.*"))
        self.core.discard(first)
        added = self.adapter.import_items([message("assistant", "new observation")], thread_id="new")
        self.core.ingest(added)
        after = self.core.package(self.stage())
        self.assertEqual(len(self.ids) + 1, len(after["evidence"]))
        self.assertEqual(2, len(set(self.archive.rglob("*.*")) - old_files))
        for key, locator in before["evidence"].items():
            self.assertEqual(locator, after["evidence"][key])
            self.assertEqual(locator["sha256"], sha256(Path(locator["file_path"]).read_bytes()).hexdigest())

    def test_reused_object_does_not_bypass_current_authorization(self):
        first = self.stage()
        self.core.discard(first)
        self.denied.add((self.ids[1], "export"))
        with self.assertRaisesRegex(WSCError, "Permission denied"):
            self.stage()

    def test_corrupt_shared_object_is_rejected_not_overwritten(self):
        first = self.stage()
        package = self.core.package(first)
        path = Path(package["evidence"][self.ids[1]]["file_path"])
        path.write_bytes(b"corrupted")
        self.core.discard(first)
        with self.assertRaisesRegex(WSCError, "evidence_object_conflict"):
            self.stage()
        self.assertEqual(b"corrupted", path.read_bytes())
        with self.assertRaisesRegex(WSCError, "exported_source_changed"):
            check_evidence(self.core, package)

    def test_detach_exports_independent_complete_handoff(self):
        op = self.stage()
        host = DurableTestHost(self.root / "host.db", self.core, self.items)
        self.core.install(op, host)
        handoff = self.root / "handoff"
        detach = self.core.stage_detach(directory=handoff, adapter=self.adapter)
        package = self.core.package(detach)
        self.assertEqual(set(self.ids), set(package["evidence"]))
        for locator in package["evidence"].values():
            self.assertTrue(Path(locator["file_path"]).is_relative_to(handoff))
            if "readable_path" in locator:
                self.assertTrue(Path(locator["readable_path"]).is_relative_to(handoff))
        check_evidence(self.core, package)

    def test_atomic_object_publication_survives_competing_writers(self):
        path = self.root / "shared-object"
        payload = b"exact historical bytes" * 8192
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: publish_object(path, payload), range(8)))
        self.assertEqual(payload, path.read_bytes())
        self.assertFalse(list(self.root.glob(".pending-*")))
        with self.assertRaisesRegex(WSCError, "evidence_object_conflict"):
            publish_object(path, b"different")
        self.assertEqual(payload, path.read_bytes())

    def test_failed_write_does_not_expose_a_partial_object(self):
        path = self.root / "never-committed"
        with patch("wsc.content_archive.os.fsync", side_effect=OSError("disk_failure")):
            with self.assertRaisesRegex(OSError, "disk_failure"):
                publish_object(path, b"content")
        self.assertFalse(path.exists())
        self.assertFalse(list(self.root.glob(".pending-*")))


if __name__ == "__main__":
    unittest.main()
