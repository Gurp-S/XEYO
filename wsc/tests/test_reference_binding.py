"""Moved lines resolve by exact content; absent, ambiguous and changed sources stay unknown."""
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.references import locate, check
from wsc.contracts import WSCError


class ReferenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "notes.md"

    def bind(self, current, needle="fact one\r\nfact two\r\n", **kwargs):
        self.path.write_bytes(current)
        return locate(needle, str(self.path), expected_sha256=sha256(current).hexdigest(), **kwargs)

    def test_moved_lines_relocate_with_content_and_resource_identity(self):
        b = self.bind(b"new task\n\nfact one\nfact two\nend")
        self.assertEqual("unique_content_match", b["status"])
        self.assertEqual((3, 4), (b["start_line"], b["end_line"]))
        self.assertFalse(b["historical_observation_retimed"])
        check([b])
        self.path.write_bytes(b"changed content")
        with self.assertRaisesRegex(WSCError, "reference_resource_changed"):
            check([b])

    def test_missing_ambiguous_changed_and_unreadable_never_choose_a_line(self):
        for current, status in [(b"another task", "content_missing"),
                (b"fact one\nfact two\nfact one\nfact two\n", "content_ambiguous"),
                (b"\xff", "resource_encoding_unavailable")]:
            with self.subTest(status=status):
                b = self.bind(current)
                self.assertEqual(status, b["status"])
                self.assertNotIn("start_line", b)
        b = locate("fact", str(self.path), expected_sha256="0" * 64)
        self.assertEqual("resource_version_changed", b["status"])
        self.path.unlink()
        self.assertEqual("resource_unavailable", locate("fact", str(self.path), expected_sha256="0" * 64)["status"])

    def test_explicit_local_resource_and_read_budget(self):
        b = self.bind(b"too large", max_bytes=3)
        self.assertEqual("resource_byte_budget_exhausted", b["status"])
        self.assertEqual(4, b["bytes_read"])
        with self.assertRaisesRegex(WSCError, "not_absolute"):
            locate("fact", "relative.md", expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
