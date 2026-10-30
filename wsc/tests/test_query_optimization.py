"""Status must not pay one meta query per key."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc import WSC, Store, Event
from wsc.store import getmetas, setmeta


class QueryChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = WSC(Store(self.root / 's.db', session_id='s', workspace=str(self.root)),
                        access=lambda *a: True)
        self.core.ingest([Event('a', 'observation', {}, text='alpha')])

    def test_status_reads_meta_in_one_statement(self):
        with patch('wsc.core.getmeta', side_effect=AssertionError('per-key meta read')):
            status = self.core.status()
        self.assertEqual(1, status['source_count'])
        for key in ('binding', 'mode', 'generation', 'cursor', 'head'):
            self.assertIn(key, status)

    def test_getmetas_keeps_missing_keys_as_none(self):
        with self.core.store.transaction() as db:
            setmeta(db, 'a', 1)
        with self.core.store.connect() as db:
            self.assertEqual({'a': 1, 'b': None}, getmetas(db, ('a', 'b')))
            self.assertEqual({}, getmetas(db, ()))


if __name__ == '__main__':
    main()
