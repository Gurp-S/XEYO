from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,main
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Selection
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.context import ContextCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore,ResultPolicy,ToolText
from native_context_recovery import ContextReceiver
from native_mapped_checkpoint_host import MappedCheckpointHost
from native_evidence import state
from native_rollout_snapshot import parse_rollout


class Server:
    def __init__(self,path):self.path=path;self.calls=0;self.fail=False
    def call(self,method,params,timeout=15):
        if self.fail:raise OSError('fixture before effect')
        assert method=='thread/inject_items';self.calls+=1
        with self.path.open('a',encoding='utf-8') as f:
            for item in params['items']:f.write(json.dumps(dict(type='response_item',payload=item))+'\n')
        return {}


class HostChecks(TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        work=self.root/'work';work.mkdir();self.denied=set()
        self.core=WSC(Store(self.root/'core.db',session_id='s',workspace=str(work)),access=lambda s,i,o:i not in self.denied)
        self.ctx=ContextRuntime(self.core,ResultStore(self.root/'results',session='s'),policy=ResultPolicy(enabled=True))
        wire=[dict(type='message',role='user',content=[dict(type='input_text',text='fixture control')]),
            dict(type='function_call',call_id='c',name='fixture',arguments='{}'),
            dict(type='function_call_output',call_id='c',output=json.dumps(dict(padding='x'*40000,value=7)))]
        events=CodexCheckpointAdapter().import_items(wire,thread_id='fixture')
        self.ctx.observe(events[:2]);self.result=events[-1]
        self.view=self.ctx.record_tool_result(self.result,ToolText(self.result.text,kind='json'))
        self.ctx.presented('offline-fixture',[e.id for e in events],receiver='offline-not-model')
        snapshot=self.ctx.capture();vid=self.ctx.prepare(snapshot,Selection(source_ids=(self.result.id,)),producer='offline-choice')
        self.op=self.ctx.stage(vid,directory=self.root/'exports',
                              adapter=ContextCheckpointAdapter(self.ctx));self.package=self.core.package(self.op)
        self.path=self.root/'native.jsonl';self.path.write_text(json.dumps(dict(type='session_meta',payload=dict(id='t')))+'\n')
        self.server=Server(self.path);self.port=self.port_for(self.server)
        self.bootstrap=state(parse_rollout(self.path.read_bytes()).rows)

    def port_for(self,server):
        session=SimpleNamespace(server=server,closed=False,registration=dict(workspace=self.core.store.workspace),
            opened=dict(cwd=self.core.store.workspace,thread=dict(id='t',path=str(self.path))),rollout_path=lambda:self.path)
        return ContextReceiver(session,self.ctx,self.ctx.capture())

    def host(self,**kwargs):return MappedCheckpointHost(self.port,self.root/'journal',bootstrap=self.bootstrap,**kwargs)

    def test_installs_once_and_historical_receipt_survives_closed_receiver(self):
        host=self.host();self.ctx.install(self.op,host)
        self.assertEqual(self.core.status()['cursor'],3);self.assertEqual(self.server.calls,1)
        host.install(self.package);self.assertEqual(self.server.calls,1)
        self.port.session.closed=True
        self.assertEqual(host.lookup(self.op).installed_through,3)

    def test_lost_reply_reconstructs_commit_without_replay_preserving_tail(self):
        def lost():raise TimeoutError('fixture after native persistence')
        with self.assertRaises(TimeoutError):self.ctx.install(self.op,self.host(after_import=lost))
        self.assertEqual(self.core.status()['cursor'],0)
        tail=dict(type='message',role='user',content=[dict(type='input_text',text='later native tail')])
        with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(type='response_item',payload=tail))+'\n')
        self.denied.add(self.result.id)
        restarted=Server(self.path);self.port=self.port_for(restarted)
        host=MappedCheckpointHost(self.port,self.root/'journal')
        self.ctx.reconcile(self.op,host)
        self.assertEqual(self.core.status()['cursor'],3)
        self.assertEqual(restarted.calls,0);self.assertEqual(self.server.calls,1)
        self.assertEqual(state(parse_rollout(self.path.read_bytes()).rows)[-1],tail)
        reply=self.ctx.query_tool(self.ctx.capture()).call(dict(operation='json_pointer',reference='result:'+self.view['result_id'],pointer='/value',units='json_pointer'))
        self.assertEqual(reply.status,'error')

    def test_unknown_before_effect_is_not_permission_to_replay(self):
        self.server.fail=True;host=self.host()
        with self.assertRaises(OSError):self.ctx.install(self.op,host)
        self.server.fail=False
        self.assertIsNone(host.lookup(self.op))
        with self.assertRaisesRegex(ValueError,'requires_lookup'):host.install(self.package)
        self.assertEqual(self.server.calls,0)

    def test_changed_native_prefix_rejected_without_repair(self):
        def lost():raise TimeoutError('fixture')
        host=self.host(after_import=lost)
        with self.assertRaises(TimeoutError):self.ctx.install(self.op,host)
        raw=self.path.read_bytes();self.path.write_bytes(raw.replace(b'"t"',b'"x"',1))
        with self.assertRaisesRegex(ValueError,'prefix_changed'):host.lookup(self.op)
        self.assertEqual(self.server.calls,1)

    def test_nonfresh_receiver_refused_before_injection(self):
        host=self.host()
        with self.path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(type='response_item',payload=dict(type='message',role='user',content=[])))+'\n')
        with self.assertRaisesRegex(ValueError,'not_fresh'):self.ctx.install(self.op,host)
        self.assertEqual(self.server.calls,0)

    def test_receipt_binding_or_seal_changes_rejected(self):
        host=self.host();self.ctx.install(self.op,host)
        path=self.root/'journal'/(self.op+'-receipt.json');data=json.loads(path.read_text())
        data['value']['receipt']['generation']=999;path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'journal_corrupt'):host.lookup(self.op)


if __name__=='__main__':main()
