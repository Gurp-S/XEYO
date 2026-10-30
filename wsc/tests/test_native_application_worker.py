from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_worker import ApplicationStudyWorker
from native_application_budget import StudyBudget
from native_business_delta import split
from native_evidence import FIELDS


class BusinessDeltaChecks(unittest.TestCase):
    def test_only_producer_declared_host_skill_payload_is_separated(self):
        payload = dict(type='message', role='developer', content=[dict(type='input_text',text='<skills_instructions>same text')],
            internal_chat_message_metadata_passthrough=dict(content_item_kinds=['host_skills.instructions'],
                content_item_metadata=[dict(provenance=dict(type='skills'))]))
        host = dict(type='response_item',payload=payload)
        user = deepcopy(host)
        user['payload']['role']='user'
        untagged = deepcopy(host)
        untagged['payload'].pop('internal_chat_message_metadata_passthrough')
        business, excluded = split([host,user,untagged])
        self.assertEqual(business,[user,untagged])
        self.assertEqual(len(excluded),1)
        self.assertEqual(host['payload'],payload)


class FakeSession:
    add_late = False
    def __init__(self, registration, destination):
        self.registration=registration
        self.destination=Path(destination)
        self.destination.mkdir()
        self.opened=None
        self.closed=False
        self.count=0
    def open(self):
        self.path=self.destination/'native.jsonl'
        self.path.write_text(json.dumps(dict(type='session_meta',payload=dict(id='fixture-thread')))+'\n',encoding='utf8')
        self.opened=dict(thread=dict(id='fixture-thread',path=str(self.path)))
    def add(self):
        self.count+=1
        amount=dict.fromkeys(FIELDS,0)
        amount.update(input_tokens=1,total_tokens=1)
        record=dict(response_id=f'fixture-{self.count}',usage=amount)
        with self.path.open('a',encoding='utf8') as stream:
            stream.write(json.dumps(dict(type='token_usage_record',payload=dict(record,thread_id='fixture-thread')))+'\n')
        return record
    def execute_stage(self, request, destination, limits, record_phase, **kwargs):
        before=len(self.path.read_text().splitlines())
        record=self.add()
        area=Path(destination)
        area.mkdir()
        (area/'rollout.jsonl').write_bytes(self.path.read_bytes())
        outcome=dict(thread_id='fixture-thread',seconds=.1,completed=True,failure=None,usage_complete=True,finals=[],
            compaction=False,turn_accounting=dict(turn_id=f'turn-{self.count}',before=dict(records=before)),
            receipts=dict(response_receipts=[record],all_usage=record['usage'],response_count=1))
        record_phase(outcome)
        return outcome
    def close(self):
        if not self.closed and self.add_late:
            self.add()
        self.closed=True
        return dict(empty_confirmed=True)


class WorkerEvidenceChecks(unittest.TestCase):
    def run_worker(self, root, late):
        work=root/'workspace'
        work.mkdir()
        output=root/'output'
        job=dict(pair_id='app/r1',arm='B',conditions_sha256='f'*64,resources=dict(output=str(output),workspace=str(work)))
        limits=dict(max_total_tokens=100,max_responses=20,max_seconds=100)
        budget=StudyBudget({'app/r1/B':limits},limits)
        prepared=dict(registration=dict(model='fixture',effort='max',workspace=str(work)),
            initial_request='Full task',stages=[dict(request=f'S{i}') for i in range(1,9)])
        def grade(*args):
            raise RuntimeError('external_grader_disconnected')
        worker=ApplicationStudyWorker(dict(model='fixture',effort='max',budgets=dict(ordinary_phase=limits),
            boundaries=dict(after_stages=[2,4,6])),budget,lambda job:prepared,lambda *args:None,grade)
        journal=[]
        FakeSession.add_late=late
        with patch('native_application_worker.NativeApplicationSession',FakeSession):
            result=worker(job,journal.append)
        return result,journal,budget

    def test_grader_failure_retains_both_paid_phase_journals(self):
        with tempfile.TemporaryDirectory() as folder:
            result,journal,budget=self.run_worker(Path(folder),False)
            self.assertEqual(result['state'],'infrastructure_error')
            self.assertEqual(len(journal),2)
            self.assertEqual(result['phases'],journal)
            self.assertEqual(budget.snapshot()['study']['tokens'],2)
            self.assertEqual(result['quality']['status'],'unknown')

    def test_late_native_receipt_is_charged_and_freezes_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            result,journal,budget=self.run_worker(Path(folder),True)
            self.assertEqual(len(journal),3)
            self.assertTrue(result['late_receipts'])
            self.assertTrue(budget.snapshot()['study']['uncertain'])
            self.assertEqual(budget.snapshot()['study']['tokens'],3)
            self.assertFalse(journal[-1]['usage_complete'])


if __name__=='__main__':
    unittest.main()
