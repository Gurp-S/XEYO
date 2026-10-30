from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'benchmarks')]
from wsc import WSC,Store,Selection,Event
from wsc.resource_io import ResourceIO
from wsc.source_reference_view import MODE
from wsc.source_access import SnapshotSourceAccess
from acceptance_matrix_v1.paired_cell import NativeCheckpointHost,IndexedCheckpointAdapter


class CheckpointHostChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.core=WSC(Store(self.root/'state.db',session_id='fixture',workspace=str(self.root)),
                      access=lambda *a:True,resource_io=ResourceIO())
        self.core.ingest([Event('control','message',dict(type='message',role='user',content=[dict(type='input_text',text='original task')]),role='user',text='original task')])
        view=self.core.prepare(self.core.capture(),Selection(),producer='host-unit',source_projection=MODE)
        self.operation=self.core.stage(view,directory=self.root/'exports',archive_directory=self.root/'archive',adapter=IndexedCheckpointAdapter())
        self.port=SimpleNamespace(session=object(),owner='native-owner',_require_live=lambda:None,
            handler=SimpleNamespace(reader=SnapshotSourceAccess(self.core.store,self.core.capture(),access=self.core.access)))
        self.host=NativeCheckpointHost(self.port,[],self.root/'receiver')
        self.host.folder.mkdir()
    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_import_then_durable_receipt_confirms_core_state(self):
        with patch('acceptance_matrix_v1.paired_cell.import_fresh',return_value=dict(matched=True)) as imported:
            receipt=self.core.install(self.operation,self.host)
        imported.assert_called_once()
        self.assertTrue(receipt['evidence_accessible'])
        self.assertEqual(self.operation,self.host.lookup(self.operation).operation_id)
        with self.core.store.connect() as db:
            self.assertEqual('confirmed',db.execute('SELECT state FROM operations WHERE id=?',(self.operation,)).fetchone()[0])

    def test_failed_import_does_not_issue_success_receipt(self):
        with patch('acceptance_matrix_v1.paired_cell.import_fresh',side_effect=ValueError('import_changed')):
            with self.assertRaisesRegex(ValueError,'import_changed'):
                self.core.install(self.operation,self.host)
        self.assertIsNone(self.host.lookup(self.operation))
