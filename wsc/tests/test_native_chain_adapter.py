from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_chain_adapter import NativeChainAdapter
from native_compaction_profile import PROFILE


class Server:
    def __init__(self,session):self.session=session;self.calls=[];self.change=False
    def call(self,method,params,timeout):
        self.calls.append((method,deepcopy(params)))
        with self.session.history.open('ab') as out:
            for supplied in params['items']:
                item=deepcopy(supplied)
                if self.change:item['role']='assistant'
                item['id']='native-added'
                out.write(json.dumps(dict(type='response_item',payload=item)).encode()+b'\n')
        return {}


class Session:
    def __init__(self,root):
        self.root=root;self.work=root/'workspace';self.work.mkdir();self.closed=False
        self.registration=dict(model='fixed',effort='max',workspace='/work/actor',native_compaction_profile=PROFILE)
        self.opened=dict(cwd='/work/actor',thread=dict(id='thread'))
        self.history=root/'history.jsonl';self.history.write_text(json.dumps(dict(type='session_meta',payload=dict(id='thread')))+'\n')
        self.server=Server(self)
    def workspace_path(self):return self.work
    def rollout_path(self):return self.history
    def execute_stage(self,request,destination,limits,record_phase,*,compact=False):
        destination.mkdir()
        (destination/'rollout.jsonl').write_bytes(self.history.read_bytes())
        (destination/'events.jsonl').write_text('')
        phase=dict(completed=True,usage_complete=False,receipts=dict(response_receipts=[]),finals=[])
        record_phase(phase);return phase
    def close(self):self.closed=True;return dict(closed=True)


class NativeAdapterChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.session=Session(self.root);self.records=[]
        for name,text in [('retry_client.py','def run_batch(*a): return []\n'),('test_smoke.py','# protected\n'),('work_state.json','{}')]:
            (self.session.work/name).write_text(text)
        self.adapter=NativeChainAdapter(lambda remaining:self.session,self.root/'adapter',model='fixed',effort='max',
            entry='retry_client.py',public_test_sha256=sha256((self.session.work/'test_smoke.py').read_bytes()).hexdigest())
        self.remaining=lambda:dict(max_total_tokens=1000,max_responses=3,max_seconds=10)
        self.initial=[dict(type='message',role='user',content=[dict(type='input_text',text='initial')])]

    def open(self):self.adapter.open(self.initial,self.remaining,self.records.append)

    def test_initial_and_incremental_import_preserve_thread_and_exact_source_fields(self):
        self.open();self.adapter.append_events(self.initial,1,self.remaining,self.records.append)
        self.assertEqual(['thread','thread'],[p['threadId'] for _,p in self.session.server.calls])
        self.assertEqual('user',self.session.server.calls[0][1]['items'][0]['role'])
        proof=json.loads((self.root/'adapter/round-1-import/proof.json').read_text())
        self.assertTrue(proof['native_import']['matched'])
        self.assertFalse(self.adapter.real_dispatch_qualified)
        with self.assertRaisesRegex(ValueError,'round_order'):self.adapter.append_events(self.initial,1,self.remaining,self.records.append)

    def test_rewritten_import_rejected_without_model(self):
        self.session.server.change=True
        with self.assertRaisesRegex(ValueError,'items_changed'):self.open()

    def test_changed_owner_rejected_before_next_call(self):
        self.open();self.session.opened['thread']['id']='other'
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            self.adapter.append_events(self.initial,1,self.remaining,self.records.append)
        self.assertEqual(1,len(self.session.server.calls))

    def test_closed_turn_copy_pins_version_and_public_test_hash(self):
        self.open();self.adapter.last_round=2
        snapshot=self.adapter.continue_task('fixture',2,self.remaining,self.records.append)
        self.assertEqual([],snapshot['errors']);self.assertTrue(snapshot['public_test_preserved'])
        frozen=Path(snapshot['files']['retry_client.py']['path'])
        previous=frozen.read_bytes();(self.session.work/'retry_client.py').write_text('changed')
        self.assertEqual(previous,frozen.read_bytes())
        (self.session.work/'test_smoke.py').write_text('changed')
        snapshot=self.adapter._snapshot(4,{})
        self.assertFalse(snapshot['public_test_preserved'])

    def test_missing_native_compaction_evidence_is_not_a_success(self):
        self.open();self.adapter.last_round=1
        proof=self.adapter.compress(1,self.remaining,self.records.append)
        self.assertFalse(proof['confirmed']);self.assertFalse(proof['summary_content_inspected'])


if __name__=='__main__':main()
