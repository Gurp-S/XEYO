"""Durability checks for the opt-in single-transaction result path."""
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from unittest import TestCase,main
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
from wsc import WSC,Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore,ResultPolicy,ToolText


class Crash(BaseException):pass


class DurableResultChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.adapter=CodexCheckpointAdapter();self.n=0
        self.core,self.results,self.ctx=self.runtime()

    def runtime(self,fault=None):
        core=WSC(Store(self.root/'core.db',session_id='session',workspace=str(self.root)),
                 access=lambda s,k,a:True)
        results=ResultStore(self.root/'results',session='session',access=lambda s,k,a:True)
        return core,results,ContextRuntime(core,results,policy=ResultPolicy(enabled=True),
                                           durable_results=True,fault=fault)

    def count(self,table,where='1=1'):
        with self.core.store.connect() as db:
            return db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+where).fetchone()[0]

    def ev(self,event):return self.count('events',"id='"+event.id+"'")

    def result(self,i=1,text=None):
        raw=text or ('中文🙂\r\nINFO row\n'*4000)
        self.ctx.observe(self.adapter.import_items(
            [dict(type='function_call',call_id='c'+str(i),name='f',arguments='{}')],
            thread_id='t',start_ordinal=self.n));self.n+=1
        event=self.adapter.import_items(
            [dict(type='function_call_output',call_id='c'+str(i),output=raw)],
            thread_id='t',start_ordinal=self.n)[0];self.n+=1
        return event,ToolText(raw,kind='terminal_log')

    def crash(self,point):
        def fault(actual):
            if actual==point:raise Crash(point)
        return fault

    def test_commit_is_one_transaction_and_duplicate_is_idempotent(self):
        event,value=self.result()
        view=self.ctx.record_tool_result(event,value)
        self.assertTrue(view['external'])
        self.assertEqual(1,self.count('events',"id='"+event.id+"'"))
        self.assertEqual(1,self.count('wsc_context_delivery_v1'))
        self.assertEqual(1,self.count('wsc_context_results_v1'))
        self.assertEqual(1,self.count('wsc_context_intents_v1',"state='committed'"))
        again=self.ctx.record_tool_result(event,value)
        self.assertEqual(view,again)
        self.assertEqual(1,self.ev(event))
        self.assertEqual(1,self.count('wsc_context_delivery_v1'))

    def test_same_call_different_content_is_rejected(self):
        event,value=self.result()
        self.ctx.record_tool_result(event,value)
        other=ToolText('other content\n'*4000,kind='terminal_log')
        with self.assertRaisesRegex(Exception,'tool_result_call_identity_conflict'):
            self.ctx.record_tool_result(replace(event,id=event.id+'-other',text=other.text),other)

    def test_blob_failure_aborts_without_event_or_claim(self):
        event,value=self.result()
        import wsc.tool_results.storage as storage
        original=storage.ResultStore.capture
        def full(self,*a,**k):raise OSError(28,'No space left on device')
        storage.ResultStore.capture=full
        try:
            view=self.ctx.record_tool_result(event,value)
        finally:
            storage.ResultStore.capture=original
        self.assertFalse(view.get('external'))
        self.assertEqual('OSError',view['externalization_error'])
        self.assertEqual(0,self.ev(event))
        self.assertEqual(0,self.count('wsc_context_results_v1'))
        self.assertEqual(0,self.count('wsc_context_delivery_v1'))
        self.assertEqual(1,self.count('wsc_context_intents_v1',"state='aborted'"))
        retry=self.ctx.record_tool_result(event,value)
        self.assertTrue(retry['external'])

    def test_crash_before_blob_leaves_no_rows_and_recovers_clean(self):
        event,value=self.result()
        with self.assertRaises(Crash):
            self.runtime(self.crash('before_blob'))[2].record_tool_result(event,value)
        self.assertEqual(0,self.ev(event))
        self.assertEqual(0,self.count('wsc_context_results_v1'))
        _,_,ctx=self.runtime()
        self.assertEqual(0,self.ev(event))
        self.assertEqual(1,self.count('wsc_context_intents_v1',"state='aborted'"))
        self.assertTrue(ctx.record_tool_result(event,value)['external'])

    def test_crash_after_blob_recovers_the_commit(self):
        event,value=self.result()
        with self.assertRaises(Crash):
            self.runtime(self.crash('after_blob'))[2].record_tool_result(event,value)
        self.assertIsNotNone(self.results.find(event.call_id))
        self.assertEqual(0,self.ev(event))
        _,_,ctx=self.runtime()
        self.assertEqual(0,ctx.recover()['scanned'])
        self.assertEqual(1,self.ev(event))
        self.assertEqual(1,self.count('wsc_context_delivery_v1'))
        self.assertEqual(1,self.count('wsc_context_results_v1'))
        view=ctx.delivery(event.id)
        self.assertTrue(view['external'])

    def test_crash_before_commit_rolls_back_then_recovers(self):
        event,value=self.result()
        with self.assertRaises(Crash):
            self.runtime(self.crash('before_commit'))[2].record_tool_result(event,value)
        self.assertEqual(0,self.ev(event))
        self.assertEqual(0,self.count('wsc_context_delivery_v1'))
        self.assertIsNotNone(self.results.find(event.call_id))
        _,_,ctx=self.runtime()
        self.assertEqual(1,self.ev(event))
        self.assertEqual(0,ctx.recover()['scanned'])

    def test_corrupt_blob_blocks_recovery_instead_of_faking_text(self):
        event,value=self.result()
        with self.assertRaises(Crash):
            self.runtime(self.crash('after_blob'))[2].record_tool_result(event,value)
        target=next(self.results.objects.glob('*.txt'))
        target.write_bytes(b'tampered')
        _,_,ctx=self.runtime()
        self.assertEqual(1,ctx.recover()['blocked'])
        self.assertEqual(0,self.ev(event))
        self.assertEqual(1,self.count('wsc_context_intents_v1',"state='recovery_required'"))


if __name__=='__main__':main()
