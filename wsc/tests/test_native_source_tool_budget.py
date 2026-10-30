from pathlib import Path
import sys,tempfile,unittest,copy,json
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parents[1]/'experiments')]
from wsc import WSC,Store,Event,WSCError
from wsc.source_access import SnapshotSourceAccess
from native_source_tool import SourceToolHandler
from native_source_tool_budget import BudgetResultSourceToolHandler


class BudgetResultTests(unittest.TestCase):
    def make(self,path,kind):
        core=WSC(Store(path,session_id='s',workspace=str(path.parent)),access=lambda *a:True)
        core.ingest([Event('a','observation',{},text='original nonce')])
        return kind(SnapshotSourceAccess(core.store,core.capture(),access=core.access))
    def event(self,n):
        return {'id':n,'method':'item/tool/call','params':{'threadId':'t','turnId':'u','callId':'c'+str(n),
            'tool':'WSCSource','arguments':{'operation':'read','source':'s1'}}}
    def test_before_after_limit_retains_access_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=self.make(Path(tmp)/'old.db',SourceToolHandler);new=self.make(Path(tmp)/'new.db',BudgetResultSourceToolHandler)
            original=None
            for n in range(8):
                before=old.handle(self.event(n),thread_id='t',turn_id='u')
                after=new.handle(self.event(n),thread_id='t',turn_id='u')
                self.assertEqual(before,after)
                if n==0:original=after
            with self.assertRaisesRegex(WSCError,'callback_budget_exhausted'):old.handle(self.event(8),thread_id='t',turn_id='u')
            for n in range(8,1008):
                reply=new.handle(self.event(n),thread_id='t',turn_id='u')
                self.assertFalse(reply['result']['success'])
                self.assertEqual({'status':'error','code':'source_tool_callback_budget_exhausted'},json.loads(reply['result']['contentItems'][0]['text']))
            self.assertEqual(8,new.reader.calls);self.assertEqual(8,len(new.seen));self.assertEqual(8,len(new.trace))
            self.assertEqual(original,new.handle(self.event(0),thread_id='t',turn_id='u'))
            bad=self.event(8);bad['params']['turnId']='other'
            with self.assertRaisesRegex(WSCError,'binding_invalid'):new.handle(bad,thread_id='t',turn_id='u')
            bad=self.event(0);bad['params']['arguments']['source']='changed'
            with self.assertRaisesRegex(WSCError,'identity_conflict'):new.handle(bad,thread_id='t',turn_id='u')


if __name__=='__main__':unittest.main()
