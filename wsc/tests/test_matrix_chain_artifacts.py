from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase,main

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.chain_artifacts import evaluate_snapshot
from acceptance_matrix_v1.chain_dataset import build_chain
from test_matrix_chain_dataset import claims


class ArtifactChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        _,private=build_chain('T1');self.oracle=private['rounds']['2']
        source=(ROOT/'benchmarks/acceptance_matrix_v1/calibration/retry_reference.py').read_text()
        source=source.replace('not in (429, 503)','not in '+repr(tuple(self.oracle['policy']['retry_statuses'])))
        (self.root/'retry_client.py').write_text(source)
        (self.root/'work_state.json').write_text(json.dumps(self.oracle['expected_work_state']))
        (self.root/'test_smoke.py').write_text('# protected test\n')
        self.refresh()

    def refresh(self):
        self.snapshot=dict(files={name:dict(path=str(self.root/name),bytes=(self.root/name).stat().st_size,
            sha256=sha256((self.root/name).read_bytes()).hexdigest()) for name in ('retry_client.py','work_state.json','test_smoke.py')},
            errors=[],task_phase=dict(finals=[dict(type='agentMessage',phase='final_answer',text=json.dumps(dict(assertions=claims(self.oracle))))]))
        self.test_hash=self.snapshot['files']['test_smoke.py']['sha256']

    def evaluate(self):return evaluate_snapshot(self.snapshot,self.oracle,public_test_sha256=self.test_hash)

    def test_code_state_and_source_applicability_pass_together(self):
        result=self.evaluate();self.assertTrue(result['task_success'],result)
        self.assertTrue(result['code']['success']);self.assertTrue(result['state']['success']);self.assertTrue(result['claims']['success'])

    def test_version_changed_during_import_is_rejected_even_when_behavior_passes(self):
        path=self.root/'retry_client.py'
        with path.open('a') as out:out.write("\nwith open(__file__, 'a') as f: f.write('\\n# changed')\n")
        self.refresh();result=self.evaluate()
        self.assertTrue(result['code']['success']);self.assertFalse(result['task_success'])
        self.assertTrue(result['errors'])

    def test_public_test_preservation_is_independent_of_adapter_flag(self):
        self.snapshot['public_test_preserved']=True
        self.test_hash='0'*64
        self.assertFalse(self.evaluate()['task_success'])

    def test_duplicate_final_json_and_stale_work_state_rejected(self):
        self.snapshot['task_phase']['finals'][0]['text']='{"assertions":[],"assertions":[]}'
        self.assertFalse(self.evaluate()['task_success'])
        (self.root/'work_state.json').write_text(json.dumps(dict(self.oracle['expected_work_state'],revision=1)))
        self.refresh();self.assertFalse(self.evaluate()['task_success'])


if __name__=='__main__':main()
