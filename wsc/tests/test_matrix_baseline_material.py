from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'experiments'),str(ROOT/'src')]
from acceptance_matrix_v1.baseline_material import import_baseline


class MaterialChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.bootstrap=[dict(type='message',role='assistant',content=[dict(type='output_text',text='bootstrap')])]
        self.session=SimpleNamespace(opened={'thread':{'path':'unused'}},registration={'workspace':str(self.folder)},server=Mock())
    def tearDown(self):self.temp.cleanup()
    def snapshot(self,items):
        return SimpleNamespace(metadata=dict(parse_complete=True),rows=[dict(type='response_item',payload=i) for i in items])
    def test_empty_is_verified_without_native_injection(self):
        with patch('acceptance_matrix_v1.baseline_material.capture_rollout',return_value=self.snapshot(self.bootstrap)):
            result=import_baseline(self.session,[],self.bootstrap,self.folder)
        self.session.server.call.assert_not_called()
        self.assertTrue(result['import_proof']['matched'])
        self.assertTrue((self.folder/'empty-history-proof.json').exists())
    def test_unexpected_history_rejected(self):
        with patch('acceptance_matrix_v1.baseline_material.capture_rollout',return_value=self.snapshot(self.bootstrap*2)):
            with self.assertRaises(ValueError):import_baseline(self.session,[],self.bootstrap,self.folder)
    def test_nonempty_uses_existing_native_import(self):
        with patch('acceptance_matrix_v1.baseline_material.import_fresh',return_value={'verified':True}) as imported:
            self.assertTrue(import_baseline(self.session,self.bootstrap,self.bootstrap,self.folder)['verified'])
        imported.assert_called_once()


if __name__=='__main__':unittest.main()
