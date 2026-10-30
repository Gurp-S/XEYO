"""Host-contract checks, not a model or native Codex quality benchmark."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from wsc import WSC,Store,Selection,Understanding,Limits
from wsc.contracts import encode,digest
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.context import ContextCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore,ResultPolicy,ToolText
from test_contracts import DurableTestHost,message


class ContextRuntimeChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.denied=set();self.result_denied=set()
        self.core=WSC(Store(self.root/'core.db',session_id='session',workspace=str(self.root)),
                      access=lambda s,k,a:k not in self.denied)
        self.store=ResultStore(self.root/'results',session='session',access=lambda s,k,a:k not in self.result_denied)
        self.ctx=ContextRuntime(self.core,self.store,policy=ResultPolicy(enabled=True))
        self.adapter=CodexCheckpointAdapter();self.ordinal=0;self.items=[]
        self.observe([message('user','Current goal and constraints')])
        self.host=DurableTestHost(self.root/'host.db',self.core,self.items)

    def observe(self,items):
        events=self.adapter.import_items(items,thread_id='native-thread',start_ordinal=self.ordinal)
        self.ordinal+=len(items);self.items.extend(items);self.ctx.observe(events)
        return events

    def result(self,i=1,*,present=True):
        raw=json.dumps(dict(value=i,needle='中🙂',padding='x'*40000),ensure_ascii=False)
        self.observe([dict(type='function_call',call_id='c'+str(i),name='fixture',arguments='{}')])
        item=dict(type='function_call_output',call_id='c'+str(i),output=raw)
        event=self.adapter.import_items([item],thread_id='native-thread',start_ordinal=self.ordinal)[0]
        self.ordinal+=1;self.items.append(item)
        view=self.ctx.record_tool_result(event,ToolText(raw,kind='json'))
        if present:self.ctx.presented('request-'+str(i),[event.id],receiver='offline-receiver')
        return event,view,raw

    def stage(self,event):
        snapshot=self.ctx.capture()
        view=self.ctx.prepare(snapshot,Selection(source_ids=(event.id,)),producer='offline-choice')
        operation=self.ctx.stage(view,directory=self.root/'exports',
                                 adapter=ContextCheckpointAdapter(self.ctx))
        return snapshot,view,operation

    def test_original_event_and_visible_projection_are_distinct_and_bound(self):
        event,view,raw=self.result();snapshot=self.ctx.capture()
        original=self.core.material(snapshot)['events'][-1]['text']
        projected=self.ctx.material(snapshot)['events'][-1]
        self.assertEqual(raw,original);self.assertNotEqual(raw,projected['text'])
        self.assertEqual('runtime_projection',projected['text_representation'])
        self.assertEqual('WSCContext',view['recovery']['tool'])
        self.assertLessEqual(len(encode(view).encode()),2048)
        query=self.ctx.query_tool(snapshot)
        source=query.query(dict(operation='describe',reference='source:s3'))
        self.assertEqual('result:'+view['result_id'],source['result_reference'])
        value=query.query(dict(operation='json_pointer',reference=source['result_reference'],units='json_pointer',pointer='/value'))
        self.assertEqual(1,value['value'])

    def test_units_are_not_guessed_or_converted(self):
        event,view,raw=self.result();query=self.ctx.query_tool(self.ctx.capture())
        position=raw.index('中')
        text=query.query(dict(operation='read',reference='source:s3',units='unicode_codepoints',offset=position,limit=2))
        self.assertEqual('中🙂',text['text'])
        for reference,units in [('source:s3','utf8_bytes'),('result:'+view['result_id'],'unicode_codepoints')]:
            with self.assertRaisesRegex(ValueError,'units_mismatch'):
                query.query(dict(operation='read',reference=reference,units=units))

    def test_both_authorities_apply_to_source_result_and_search(self):
        event,view,_=self.result();query=self.ctx.query_tool(self.ctx.capture())
        self.result_denied.add(view['result_id'])
        for ref in ('source:s3','result:'+view['result_id']):
            response=query.call(dict(operation='read',reference=ref,units='unicode_codepoints' if ref.startswith('source:') else 'utf8_bytes'))
            self.assertEqual('error',response.status)
        found=query.query(dict(operation='find',reference='source:*',units='source_index',literal='中🙂'))
        self.assertEqual([],found['matches']);self.assertFalse(found['complete'])
        self.result_denied.clear();self.denied.add(event.id)
        self.assertEqual('error',query.call(dict(operation='describe',reference='result:'+view['result_id'])).status)

    def test_future_result_is_outside_old_snapshot_and_old_ref_survives_new_snapshot(self):
        _,first,_=self.result();old=self.ctx.query_tool(self.ctx.capture())
        _,second,_=self.result(2)
        with self.assertRaisesRegex(ValueError,'outside_snapshot'):
            old.query(dict(operation='describe',reference='result:'+second['result_id']))
        new=self.ctx.query_tool(self.ctx.capture())
        self.assertEqual(1,new.query(dict(operation='json_pointer',reference='result:'+first['result_id'],units='json_pointer',pointer='/value'))['value'])

    def test_return_does_not_implicitly_mark_result_presented(self):
        event,view,_=self.result(present=False)
        with self.assertRaisesRegex(ValueError,'presentation_unknown'):self.ctx.capture()
        self.ctx.presented('actual-request',[event.id],receiver='actual-input-owner')
        self.assertEqual(3,self.ctx.capture().cut)

    def test_projection_keeps_controls_and_original_archive(self):
        event,view,raw=self.result();snapshot,vid,op=self.stage(event)
        self.assertEqual(0,self.core.status()['cursor'])
        with self.core.store.connect() as db:
            body=json.loads(db.execute('SELECT data FROM views WHERE id=?',(vid,)).fetchone()[0])['body']
        self.assertEqual(snapshot.events[0],body['sources'][0])
        self.assertNotIn('text',body['sources'][-1])
        package=self.core.package(op)
        self.assertEqual(self.items[0],package['items'][0])
        self.assertNotIn('x'*1000,encode(package['items']))
        self.assertEqual(self.items[-1],json.loads(Path(package['evidence'][event.id]['file_path']).read_text(encoding='utf-8')))
        self.assertEqual(raw,Path(package['evidence'][event.id]['readable_path']).read_text(encoding='utf-8'))

    def test_tail_keeps_call_identity_and_uses_recorded_view(self):
        first,_,_=self.result();snapshot=self.ctx.capture()
        tail,second,raw=self.result(2)
        vid=self.ctx.prepare(snapshot,Selection(source_ids=(first.id,)),producer='offline-choice')
        op=self.ctx.stage(vid,directory=self.root/'exports',adapter=ContextCheckpointAdapter(self.ctx));items=self.core.package(op)['items']
        self.assertEqual(self.items[-2],items[-2])
        self.assertEqual('c2',items[-1]['call_id']);self.assertEqual(second,json.loads(items[-1]['output']))
        self.assertNotIn(raw,encode(items))

    def test_lost_install_reply_reconciles_once_and_does_not_re_admit_old_commit(self):
        event,view,_=self.result();_,_,op=self.stage(event)
        self.host.lose_reply=True
        with self.assertRaises(TimeoutError):self.ctx.install(op,self.host)
        self.assertEqual(0,self.core.status()['cursor']);self.assertEqual(1,self.host.state()['effects'])
        self.result_denied.add(view['result_id'])
        self.ctx.reconcile(op,self.host)
        self.assertEqual(3,self.core.status()['cursor'])
        self.ctx.install(op,self.host)
        self.assertEqual(1,self.host.state()['effects'])

    def test_control_change_invalidates_candidate_and_never_ages_out_instructions(self):
        event,_,_=self.result();snapshot=self.ctx.capture()
        self.observe([message('user','Changed current requirement')])
        with self.assertRaisesRegex(ValueError,'control_changed'):
            self.ctx.prepare(snapshot,Selection(),producer='offline-choice')
        fresh=self.ctx.capture();vid=self.ctx.prepare(fresh,Selection(),producer='offline-choice')
        with self.core.store.connect() as db:body=json.loads(db.execute('SELECT data FROM views WHERE id=?',(vid,)).fetchone()[0])['body']
        self.assertEqual(2,sum(r.get('role')=='user' for r in body['sources']))

    def test_source_and_external_corruption_are_not_hidden_by_references(self):
        event,view,_=self.result();query=self.ctx.query_tool(self.ctx.capture())
        with self.core.store.transaction() as db:
            db.execute('UPDATE events SET data=replace(data,?,?) WHERE id=?',('padding','paddinh',event.id))
        response=query.call(dict(operation='read',reference='result:'+view['result_id'],units='utf8_bytes'))
        self.assertEqual('error',response.status);self.assertIn('source_integrity_mismatch',response.text)

    def test_repeated_folds_preserve_old_refs_cas_and_cumulative_query_budget(self):
        self.ctx.max_queries=8;first=None
        for i in range(1,7):
            event,visible,_=self.result(i);first=first or visible['result_id']
            snapshot=self.ctx.capture()
            record=Understanding(text='observation '+str(i),kind='working_observation',sources=(event.id,),
                 scope={'current_applicability':'unverified'},id='u',expected_revision=i-1 if i>1 else None)
            vid=self.ctx.prepare(snapshot,Selection(source_ids=(event.id,),new_understandings=(record,)),producer='offline-model-fixture')
            op=self.ctx.stage(vid,directory=self.root/'exports',adapter=ContextCheckpointAdapter(self.ctx));self.ctx.install(op,self.host)
            value=self.ctx.query_tool(self.ctx.capture()).query(dict(operation='json_pointer',reference='result:'+first,units='json_pointer',pointer='/value'))
            self.assertEqual(1,value['value'])
        self.assertEqual(6,self.core.status()['generation']);self.assertEqual(13,self.core.status()['cursor'])
        self.assertEqual(6,self.ctx.query_calls)
        query=self.ctx.query_tool(self.ctx.capture())
        for _ in range(2):query.query(dict(operation='describe',reference='result:'+first))
        with self.assertRaisesRegex(ValueError,'call_limit'):query.query(dict(operation='describe',reference='result:'+first))
        self.assertEqual(6,self.host.state()['effects'])

    def test_external_store_cannot_silently_switch_source_workspace(self):
        other=WSC(Store(self.root/'other.db',session_id='session',workspace=str(self.root/'other')),access=lambda *_:True)
        with self.assertRaisesRegex(ValueError,'workspace_binding_mismatch'):
            ContextRuntime(other,self.store,policy=ResultPolicy(enabled=True))

    def test_source_sequence_changes_invalidate_original_result_link(self):
        event,visible,_=self.result();query=self.ctx.query_tool(self.ctx.capture())
        with self.core.store.transaction() as db:db.execute('UPDATE events SET seq=99 WHERE id=?',(event.id,))
        value=query.call(dict(operation='read',reference='result:'+visible['result_id'],units='utf8_bytes'))
        self.assertEqual('error',value.status);self.assertIn('source_binding_changed',value.text)

    def test_identical_result_delivery_replay_is_idempotent(self):
        first,_,raw=self.result()
        self.observe([dict(type='function_call',call_id='duplicate',name='fixture',arguments='{}')])
        event=self.adapter.import_items([dict(type='function_call_output',call_id='duplicate',output=raw)],
                    thread_id='native-thread',start_ordinal=self.ordinal)[0]
        visible=self.ctx.record_tool_result(event,ToolText(raw,kind='json'))
        self.assertIn('dedupe_identical',visible['rules'])
        self.assertEqual(visible,self.ctx.record_tool_result(event,ToolText(raw,kind='json')))


if __name__=='__main__':main()
