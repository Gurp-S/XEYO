"""An oversized view is rejected before its public projection is built."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc import WSC, Store, Event, Limits, WSCError
from wsc.contracts import Generated, Selection
from wsc.material_v2 import public_material as real_public


class ProjectionChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = WSC(Store(self.root / 's.db', session_id='s', workspace=str(self.root)),
                        access=lambda *a: True)
        self.core.ingest([Event('a', 'observation', {}, text='x' * 2000)])

    def test_oversized_view_is_rejected_without_projecting(self):
        calls = []

        def counting(prefix, records):
            calls.append(1)
            return real_public(prefix, records)

        with patch('wsc.material_v2.public_material', counting):
            with self.assertRaisesRegex(WSCError, 'material_byte_budget'):
                self.core.generate(self.core.capture(), lambda m: Generated(Selection()),
                                   producer='p', limits=Limits(max_material_bytes=100))
        self.assertEqual([], calls, 'the projection was built before the budget check')

    def test_a_fitting_view_still_projects(self):
        self.core.generate(self.core.capture(), lambda m: Generated(Selection()),
                           producer='p', limits=Limits(max_material_bytes=10000))


if __name__ == '__main__':
    main()
