import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_application_worker import ApplicationStudyWorker
from native_application_budget import StudyBudget
from native_evidence import FIELDS


class SharedSession:
    calls=[]
    injections=[]
    def __init__(self,registration,destination):
        self.registration=registration
        self.destination=Path(destination)
        self.destination.mkdir()
        self.closed=False
        self.count=0
        self.server=self
    def open(self):
        self.tid='fixture-'+self.destination.name
        self.path=self.destination/'native.jsonl'
        self.path.write_text(json.dumps(dict(type='session_meta',payload=dict(id=self.tid)))+'\n')
        self.opened=dict(thread=dict(id=self.tid,path=str(self.path)))
    def source_manifest(self):return {}
    def call(self,method,params):
        assert method=='thread/inject_items'
        self.injections.extend((len(self.calls),item) for item in params['items'])
        with self.path.open('a') as stream:
            for item in params['items']:
                stream.write(json.dumps(dict(type='response_item',payload=item))+'\n')
        return {}
    def execute_stage(self,request,destination,limits,record_phase,**kwargs):
        self.calls.append(request)
        before=len(self.path.read_text().splitlines())
        self.count+=1
        value=dict.fromkeys(FIELDS,0)
        value.update(input_tokens=1,total_tokens=1)
        receipt=dict(response_id=self.tid+'-'+str(self.count),usage=value)
        with self.path.open('a') as stream:
            stream.write(json.dumps(dict(type='token_usage_record',payload=dict(receipt,thread_id=self.tid)))+'\n')
        area=Path(destination);area.mkdir()
        (area/'rollout.jsonl').write_bytes(self.path.read_bytes())
        phase=dict(thread_id=self.tid,seconds=.1,completed=True,failure=None,usage_complete=True,
            turn_accounting=dict(before=dict(records=before),turn_id='turn-'+str(self.count)),
            receipts=dict(response_receipts=[receipt],response_count=1,all_usage=value))
        record_phase(phase)
        return phase
    def close(self):self.closed=True;return dict(empty_confirmed=True)


class SharedWorkerTests(unittest.TestCase):
    def test_first_operation_is_boundary_without_replaying_or_rebilling_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir()
            limits=dict(max_total_tokens=100,max_responses=100,max_seconds=100)
            budget=StudyBudget({'app/shared/B':limits},limits)
            job=dict(pair_id='app/shared',arm='B',conditions_sha256='a'*64,resources=dict(workspace=str(work),output=str(root/'output')))
            payload=dict(registration=dict(workspace=str(work),model='fixture',effort='max',parent_paths={},initial_manifest={}),
                stages=[dict(request='S'+str(i)) for i in range(1,9)],initial_request='FULL S1',
                common_prefix=dict(capsule='sealed',capsule_sha256='b'*64,reset_before_turn_id='original-turn'))
            def grade(job,index,*args):
                self.assertEqual(index,4)
                raise RuntimeError('stop_after_scope_check')
            SharedSession.calls=[]
            SharedSession.injections=[]
            worker=ApplicationStudyWorker(dict(model='fixture',effort='max',budgets=dict(ordinary_phase=limits,boundary_phase=limits),
                boundaries=dict(after_stages=[2,4,6])),budget,lambda job:payload,lambda *args:None,grade)
            journal=[]
            with patch('native_application_worker.NativeForkSession',SharedSession):
                result=worker(job,journal.append)
            self.assertEqual(SharedSession.calls,['native_compaction','S3','S4'])
            self.assertEqual(budget.snapshot()['study']['tokens'],3)
            self.assertEqual(len(journal),3)
            self.assertFalse(result['shared_prefix']['shared_usage_charged'])


    def test_shared_evaluation_fact_arrives_before_native_compaction(self):
        fact=dict(kind='shared_S2_evaluation_facts_v2',scope='fixture_only')
        with patch('native_paired_evaluation.load_facts',return_value=fact):
            self.test_first_operation_is_boundary_without_replaying_or_rebilling_prefix()
        matching=[position for position,item in SharedSession.injections
            if item.get('content') and json.loads(item['content'][0]['text'])==fact]
        self.assertEqual([0],matching)
        self.assertEqual('native_compaction',SharedSession.calls[0])


if __name__=='__main__':unittest.main()
