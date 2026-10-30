from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import save, manifest, file_hash
from native_private_input_reuse import verify


class PrivateInputReuseTests(unittest.TestCase):
    def test_source_and_closed_zero_execution_receipts_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            work=root/'workspace'
            work.mkdir()
            (work/'app.py').write_text('original',encoding='utf8')
            binding=dict(source_manifest=manifest(work))
            prepared=root/'prepared.json'
            result=root/'result.json'
            save(prepared,dict(registration=dict(workspace=str(work)),binding_sha256='bound'))
            save(result,dict(state='infrastructure_error',phases=[],admission_matched=False,
                cleanup=[dict(empty_confirmed=True)]))
            spec=dict(workspace=str(work),prepared=str(prepared),prepared_sha256=file_hash(prepared),
                result=str(result),result_sha256=file_hash(result),binding_sha256='bound')
            job=dict(resources=dict(workspace=str(work)))
            self.assertTrue(verify(spec,job,binding)['source_reverified'])
            (work/'app.py').write_text('changed',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'source_changed'):
                verify(spec,job,binding)

    def test_task_execution_cannot_be_reused_as_an_unexecuted_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            work=root/'workspace'
            work.mkdir()
            prepared=root/'prepared.json'
            result=root/'result.json'
            save(prepared,dict(registration=dict(workspace=str(work)),binding_sha256='bound'))
            save(result,dict(state='infrastructure_error',phases=[dict(response_count=1)],
                admission_matched=False,cleanup=[dict(empty_confirmed=True)]))
            spec=dict(workspace=str(work),prepared=str(prepared),prepared_sha256=file_hash(prepared),
                result=str(result),result_sha256=file_hash(result),binding_sha256='bound')
            with self.assertRaisesRegex(ValueError,'not_unexecuted'):
                verify(spec,dict(resources=dict(workspace=str(work))),dict(source_manifest={}))


if __name__=='__main__':
    unittest.main()
