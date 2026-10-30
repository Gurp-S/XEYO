"""A restart must not refill the cumulative source-access budget."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
from wsc import WSC, Store, Event, WSCError
from wsc.source_access import SnapshotSourceAccess, SourceAccessLimits


class RestartBudgetChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = WSC(Store(self.root / 'state.db', session_id='s', workspace=str(self.root)),
                        access=lambda *a: True)
        self.core.ingest([Event('a', 'observation', {}, text='alpha'),
                          Event('b', 'observation', {}, text='beta')])
        self.snapshot = self.core.capture()

    def reader(self, limits):
        return SnapshotSourceAccess(self.core.store, self.snapshot, access=lambda *a: True, limits=limits)

    def test_spend_survives_the_reader_and_blocks_the_next_one(self):
        limits = SourceAccessLimits(max_calls=2)
        first = self.reader(limits)
        first.read('s1')
        first.read('s1')
        first.reset()  # query boundary: the spend is persisted here

        second = self.reader(limits)
        with self.assertRaisesRegex(WSCError, 'call_budget'):
            second.read('s1')

    def test_below_the_ceiling_a_restarted_reader_still_reads(self):
        limits = SourceAccessLimits(max_calls=3)
        first = self.reader(limits)
        first.read('s1')
        first.reset()

        second = self.reader(limits)
        self.assertEqual('alpha', second.read('s1')['text'])

    def test_a_new_boundary_does_not_reset_the_budget(self):
        limits = SourceAccessLimits(max_calls=2)
        first = self.reader(limits)
        first.read('s1')
        first.read('s1')
        first.reset()

        self.core.ingest([Event('c', 'observation', {}, text='gamma')])
        moved = self.core.capture()
        second = SnapshotSourceAccess(self.core.store, moved, access=lambda *a: True, limits=limits)
        with self.assertRaisesRegex(WSCError, 'call_budget'):
            second.read('s1')


if __name__ == '__main__':
    main()
