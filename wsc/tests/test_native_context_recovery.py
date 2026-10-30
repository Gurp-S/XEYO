from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from hashlib import sha256
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Event
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore
from native_context_recovery import open_context_receiver
from native_task_recovery import TaskReceiver


class FakeRPC:
    def __init__(self,root):self.root=root;self.commands=[];self.bad=False
    def call(self,method,params,timeout):
        self.commands.append((method,params))
        path=params['command'][-1];raw=(self.root/Path(path).name).read_bytes()
        return dict(exitCode=0,stdout='/work/actor\n'+('0'*64 if self.bad else sha256(raw).hexdigest())+'  '+path+'\n')


class FakeSession:
    def __init__(self,workspace,root):
        self.registration={'workspace':workspace};self.opened={'cwd':workspace,'thread':{'id':'receiver'}}
        self.server=FakeRPC(root);self.closed=False;self.executions=0
    def close(self):self.closed=True
    def execute_stage(self,request,destination,limits,record_phase,*,output_schema,tool_handler):
        self.executions+=1;turn='t'+str(self.executions)
        event=dict(id=1,method='item/tool/call',params=dict(threadId='receiver',turnId=turn,
             callId='same-local-id',tool='WSCContext',arguments=dict(operation='read',reference='source:s1',units='unicode_codepoints')))
        result=tool_handler.handle(event,thread_id='receiver',turn_id=turn);record_phase(result);return result


class NativeContextChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'actor-root';(self.root/'actor').mkdir(parents=True)
        self.core=WSC(Store(Path(self.temp.name)/'core.db',session_id='s',workspace=str(self.root/'actor')),access=lambda *_:True)
        self.core.ingest([Event('observation','observation',{},text='historical original')])
        self.ctx=ContextRuntime(self.core,ResultStore(Path(self.temp.name)/'results',session='s'),max_queries=2)
        self.snapshot=self.ctx.capture();self.session=FakeSession('/work/actor',self.root);self.options=[]
        def factory(**kwargs):self.options.append(kwargs);return self.session
        self.factory=factory

    def test_cross_namespace_old_port_rejects_new_explicit_mapping_passes(self):
        with self.assertRaisesRegex(ValueError,'workspace_mismatch'):
            TaskReceiver(self.session,self.ctx.query_tool(self.snapshot).reader)
        port=open_context_receiver(self.factory,self.ctx,self.snapshot,actor_root=self.root)
        reply=port.execute_stage('fixture',Path('unused'),{},lambda x:None,capacity_check=lambda *a:True)
        self.assertTrue(reply['result']['success'])
        self.assertEqual('historical original',json.loads(reply['result']['contentItems'][0]['text'])['text'])
        self.assertEqual(str(self.root/'actor'),self.core.store.workspace)
        self.assertEqual('/work/actor',port.workspace)
        self.assertEqual(['WSCContext'],[d['name'] for d in self.options[0]['dynamic_tools']])
        self.assertIsNone(self.options[0]['selector_runtime'])

    def test_wrong_marker_rejects_and_closes_without_source_io(self):
        self.session.server.bad=True
        with self.assertRaisesRegex(ValueError,'mapping_unverified'):
            open_context_receiver(self.factory,self.ctx,self.snapshot,actor_root=self.root)
        self.assertTrue(self.session.closed);self.assertEqual(0,self.ctx.query_calls)

    def test_changed_marker_cwd_or_owner_is_rejected_before_query(self):
        for what in ('marker','cwd','owner'):
            session=FakeSession('/work/actor',self.root)
            port=open_context_receiver(lambda **k:session,self.ctx,self.snapshot,actor_root=self.root)
            if what=='marker':Path(port.binding.marker).write_bytes(b'changed')
            elif what=='cwd':session.opened['cwd']='/work/other'
            else:session.opened['thread']['id']='other'
            with self.assertRaises(ValueError):
                port.execute_stage('fixture',Path('unused'),{},lambda x:None,capacity_check=lambda *a:True)
        self.assertEqual(0,self.ctx.query_calls)

    def test_snapshot_advance_never_resets_budget_and_new_turn_ids_are_distinct(self):
        port=open_context_receiver(self.factory,self.ctx,self.snapshot,actor_root=self.root)
        for _ in range(2):
            self.assertTrue(port.execute_stage('fixture',Path('unused'),{},lambda x:None,capacity_check=lambda *a:True)['result']['success'])
            port.advance(self.snapshot)
        self.assertFalse(port.execute_stage('fixture',Path('unused'),{},lambda x:None,capacity_check=lambda *a:True)['result']['success'])
        self.assertEqual(2,self.ctx.query_calls);self.assertEqual(2,len(port.handler.seen))

    def test_callback_replay_is_exact_and_changed_arguments_or_owner_reject(self):
        port=open_context_receiver(self.factory,self.ctx,self.snapshot,actor_root=self.root)
        event=dict(id='rpc-id',method='item/tool/call',params=dict(threadId='receiver',turnId='turn',callId='call',tool='WSCContext',
             arguments=dict(operation='read',reference='source:s1',units='unicode_codepoints')))
        first=port.handler.handle(event,thread_id='receiver',turn_id='turn')
        self.assertEqual(first,port.handler.handle(event,thread_id='receiver',turn_id='turn'))
        self.assertEqual(1,self.ctx.query_calls)
        event['params']['arguments']['offset']=1
        with self.assertRaisesRegex(ValueError,'identity_conflict'):port.handler.handle(event,thread_id='receiver',turn_id='turn')
        with self.assertRaisesRegex(ValueError,'binding_invalid'):port.handler.handle(event,thread_id='other',turn_id='turn')

    def test_capacity_still_required_and_host_path_mode_remains_available(self):
        self.session=FakeSession(self.core.store.workspace,self.root)
        port=open_context_receiver(self.factory,self.ctx,self.snapshot)
        with self.assertRaisesRegex(ValueError,'capacity_unverified'):
            port.execute_stage('fixture',Path('unused'),{},lambda x:None)
        self.assertEqual(0,self.session.executions)

    def test_opt_in_coordinate_policy_survives_advance_without_resetting_budget(self):
        port=open_context_receiver(self.factory,self.ctx,self.snapshot,actor_root=self.root,
                                   infer_json_pointer_units=True)
        definition=self.options[0]['dynamic_tools'][0]
        self.assertIn('omitted units equals json_pointer',definition['description'])
        port.query.query(dict(operation='read',reference='source:s1',units='unicode_codepoints'))
        self.core.ingest([Event('later','observation',{},text='later observation')])
        port.advance(self.ctx.capture())
        self.assertTrue(port.query.infer_json_pointer_units)
        self.assertEqual(definition,port.query.definition())
        self.assertEqual(1,self.ctx.query_calls)


if __name__=='__main__':main()
