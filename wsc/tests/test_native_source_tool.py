from pathlib import Path
import sys,tempfile,unittest,copy,json
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parents[1]/'experiments')]
from wsc import WSC,Store,Event,WSCError
from wsc.source_access import SnapshotSourceAccess
from native_source_tool import SourceToolHandler,checked_description


class SourceToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True)
        core.ingest([Event('original','observation',{},text='receipt A: original value')])
        self.reader=SnapshotSourceAccess(core.store,core.capture(),access=core.access);self.handler=SourceToolHandler(self.reader)
        self.event={'id':7,'method':'item/tool/call','params':{'threadId':'t','turnId':'u','callId':'call-1','tool':'WSCSource','arguments':{'operation':'read','source':'s1'}}}
    def test_bound_read_is_idempotent_and_no_extra_permission(self):
        reply=self.handler.handle(self.event,thread_id='t',turn_id='u');value=json.loads(reply['result']['contentItems'][0]['text'])
        self.assertTrue(reply['result']['success']);self.assertEqual('receipt A: original value',value['text'])
        self.assertEqual(reply,self.handler.handle(self.event,thread_id='t',turn_id='u'))
        self.assertEqual(1,self.reader.calls)
        altered=copy.deepcopy(self.event);altered['params']['arguments']['source']='other'
        with self.assertRaisesRegex(WSCError,'identity_conflict'):self.handler.handle(altered,thread_id='t',turn_id='u')
    def test_cross_turn_and_extra_path_never_read(self):
        with self.assertRaisesRegex(WSCError,'binding_invalid'):self.handler.handle(self.event,thread_id='t',turn_id='other')
        self.assertEqual(0,self.reader.calls)
        event=copy.deepcopy(self.event);event['params']['arguments']['path']='C:/not-bound'
        reply=self.handler.handle(event,thread_id='t',turn_id='u')
        self.assertFalse(reply['result']['success']);self.assertEqual(0,self.reader.calls)
    def test_wrong_snapshot_descriptor_never_reaches_model(self):
        bound=self.reader.snapshot_binding
        offered={'session_id':bound['session_id'],'frontier_boundary':{'current_cut':bound['cut'],'source_digest':bound['source_digest']}}
        description=self.handler.describe();public=checked_description(offered,description)
        self.assertNotIn('engine_binding',public);self.assertIn('engine_binding',description)
        for key,value in [('session_id','other'),('cut',False),('source_digest','changed')]:
            altered=copy.deepcopy(description);altered['engine_binding'][key]=value
            with self.assertRaisesRegex(WSCError,'snapshot_binding_mismatch'):checked_description(offered,altered)


if __name__=='__main__':unittest.main()
