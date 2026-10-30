"""One call must expose every counter the store and process keep."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc import WSC, Store, Event, Limits
from wsc.contracts import Generated, Selection
from wsc.resource_io import ResourceIO


class MetricChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.io = ResourceIO()
        self.core = WSC(Store(self.root / 's.db', session_id='s', workspace=str(self.root)),
                        access=lambda *a: True, resource_io=self.io)

    def test_metrics_aggregates_usage_io_and_operations(self):
        self.core.ingest([Event('a', 'observation', {}, text='alpha')])
        self.core.generate(self.core.capture(), lambda m: Generated(Selection()),
                           producer='p', limits=Limits())
        metrics = self.core.metrics()
        self.assertEqual({'usage', 'io_bytes_read', 'operations'}, set(metrics))
        self.assertIn('output', metrics['usage'])
        self.assertIsInstance(metrics['operations'], int)
        self.assertIsInstance(metrics['io_bytes_read'], int)

    def test_metrics_without_resource_io_reports_zero(self):
        core = WSC(Store(self.root / 'plain.db', session_id='s', workspace=str(self.root)),
                   access=lambda *a: True)
        self.assertEqual(0, core.metrics()['io_bytes_read'])


if __name__ == '__main__':
    main()
