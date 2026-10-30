"""Bounded reads must stop at a deadline instead of running to completion."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest import TestCase, main
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc.contracts import WSCError
from wsc.resource_io import ResourceIO


class DeadlineChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = bytes(range(256)) * 1024
        self.path = self.root / 'blob'
        self.path.write_bytes(self.payload)
        self.io = ResourceIO(chunk_bytes=1024)

    def test_expired_deadline_aborts_the_read(self):
        with self.assertRaisesRegex(WSCError, 'resource_read_deadline_exceeded'):
            self.io.read_bounded(self.path, len(self.payload), deadline=monotonic() - 1)
        self.assertEqual(0, self.io.bytes_read, 'an expired deadline still read data')

    def test_generous_deadline_returns_the_payload(self):
        self.assertEqual(self.payload, self.io.read_bounded(
            self.path, len(self.payload), deadline=monotonic() + 60))

    def test_digest_honours_the_deadline(self):
        with self.assertRaisesRegex(WSCError, 'resource_read_deadline_exceeded'):
            self.io.digest(self.path, deadline=monotonic() - 1)

    def test_non_numeric_deadline_is_rejected(self):
        with self.assertRaisesRegex(WSCError, 'resource_read_deadline_invalid'):
            self.io.read_bounded(self.path, 10, deadline='soon')


if __name__ == '__main__':
    main()
