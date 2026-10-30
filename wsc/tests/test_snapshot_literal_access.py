from pathlib import Path
from unittest.mock import patch
import sys,tempfile,unittest,json,copy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from wsc import WSC,Store,Event,WSCError
from wsc.source_access import SnapshotSourceAccess,SourceAccessLimits
from wsc.snapshot_literal_access import SnapshotLiteralAccess,SnapshotSearchLimits
from wsc.contracts import digest,encode
from native_source_tool import SourceToolHandler,checked_description


class SnapshotLiteralTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.allowed=True;self.access=lambda *a:self.allowed
        self.core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=self.access)
    def reader(self,**kwargs):return SnapshotLiteralAccess(self.core.store,self.core.capture(),access=self.access,**kwargs)
    def test_late_target_preserves_normal_access_budget(self):
        events=[Event(str(i),'observation',{},text='unrelated '+str(i)) for i in range(1024)]
        events[1000]=Event('1000','observation',{},text='nonce target original')
        self.core.ingest(events);snapshot=self.core.capture()
        legacy=SnapshotSourceAccess(self.core.store,snapshot,access=self.access)
        page=legacy.find('nonce target');page=legacy.find('nonce target',cursor=page['next_cursor']);page=legacy.find('nonce target',cursor=page['next_cursor'])
        self.assertFalse(page['matches']);self.assertEqual(512,page['metrics']['rows_verified'])
        reader=self.reader();page=reader.find('nonce target')
        self.assertTrue(page['complete']);self.assertEqual('s1001',page['matches'][0]['source'])
        self.assertEqual(1,page['metrics']['rows_verified']);self.assertEqual(1024,page['search_metrics']['snapshot_sources_scanned'])
        self.assertEqual('nonce target original',reader.read('1000')['text'])
    def test_permission_and_live_seal_on_matches(self):
        self.core.ingest([Event('a','observation',{},text='needle original')]);reader=self.reader()
        self.allowed=False;page=reader.find('needle');self.assertFalse(page['complete']);self.assertFalse(page['matches']);self.assertTrue(page['errors'])
        self.allowed=True
        with self.core.store.transaction() as db:db.execute("UPDATE events SET data='{}' WHERE id='a'")
        page=reader.find('needle');self.assertFalse(page['matches']);self.assertFalse(page['complete']);self.assertIn('integrity',page['errors'][0]['code'])
    def test_negative_result_is_snapshot_not_current_store_certificate(self):
        self.core.ingest([Event('a','observation',{},text='old text')]);reader=self.reader()
        with self.core.store.transaction() as db:db.execute("UPDATE events SET data='{}' WHERE id='a'")
        page=reader.find('absent');self.assertTrue(page['complete']);self.assertFalse(page['matches'])
        self.assertEqual('sealed_snapshot_public_text',page['search_basis']);self.assertEqual('returned_matches_only',page['storage_validation'])
        self.assertIn('not current storage health',reader.describe()['storage_validation'])
    def test_self_consistent_changed_row_and_unscanned_hit_never_replace_snapshot(self):
        self.core.ingest([Event('a','observation',{},text='needle original'),Event('b','observation',{},text='needle second')])
        reader=self.reader(limits=SourceAccessLimits(max_rows_total=1))
        page=reader.find('needle');self.assertEqual(1,page['next_cursor']);self.assertEqual(['s1'],[m['source'] for m in page['matches']])
        reader=self.reader()
        with self.core.store.transaction() as db:
            data=json.loads(db.execute("SELECT data FROM events WHERE id='a'").fetchone()[0]);data['text']='replacement'
            db.execute("UPDATE events SET data=?,digest=? WHERE id='a'",(encode(data),digest(data)))
        page=reader.find('needle');self.assertFalse(page['complete']);self.assertEqual(['s2'],[m['source'] for m in page['matches']])
        self.assertEqual('source_access_snapshot_changed',page['errors'][0]['code'])
    def test_permission_revocation_during_lookup_returns_no_cached_text(self):
        self.core.ingest([Event('a','observation',{},text='needle original')]);calls=[]
        def access(*args):calls.append(args);return len(calls)==1
        reader=SnapshotLiteralAccess(self.core.store,self.core.capture(),access=access)
        page=reader.find('needle');self.assertFalse(page['matches']);self.assertFalse(page['complete']);self.assertEqual(0,reader.rows_verified)
    def test_denied_text_is_not_charged_or_reported_as_byte_budget_failure(self):
        self.core.ingest([Event('a','observation',{},text='private'*100),Event('b','observation',{},text='match')])
        reader=SnapshotLiteralAccess(self.core.store,self.core.capture(),access=lambda session,source,action:source=='b',limits=SourceAccessLimits(max_text_bytes_total=10))
        page=reader.find('match');self.assertEqual(['s2'],[m['source'] for m in page['matches']])
        self.assertEqual('Permission denied: source',page['errors'][0]['code']);self.assertEqual(5,page['metrics']['public_text_bytes_examined'])
        self.assertNotIn('catalog_public_text_bytes',page['search_metrics'])
    def test_catalog_count_and_scan_deadline_are_explicit_partial_results(self):
        self.core.ingest([Event('a','observation',{},text='needle'),Event('b','observation',{},text='needle')])
        with self.assertRaisesRegex(WSCError,'source_budget'):self.reader(search_limits=SnapshotSearchLimits(max_catalog_sources=1))
        reader=self.reader()
        with patch('wsc.snapshot_literal_access.monotonic',side_effect=[0.,1.]):page=reader.find('needle')
        self.assertFalse(page['complete']);self.assertFalse(page['matches']);self.assertEqual(0,page['next_cursor'])
        self.assertEqual(0,page['metrics']['rows_verified']);self.assertEqual('snapshot_search_time_budget_exhausted',page['errors'][0]['code'])
    def test_existing_native_port_keeps_snapshot_binding_and_structured_results(self):
        self.core.ingest([Event('a','observation',{},text='needle original')]);reader=self.reader();handler=SourceToolHandler(reader)
        bound=reader.snapshot_binding
        offered=dict(session_id=bound['session_id'],frontier_boundary=dict(current_cut=bound['cut'],source_digest=bound['source_digest']))
        public=checked_description(offered,handler.describe());self.assertNotIn('engine_binding',public)
        self.assertEqual('sealed_snapshot_public_text',public['search_basis'])
        event=dict(id=1,method='item/tool/call',params=dict(threadId='t',turnId='u',callId='c',tool='WSCSource',arguments=dict(operation='find',literal='needle')))
        reply=handler.handle(event,thread_id='t',turn_id='u');self.assertTrue(reply['result']['success'])
        result=json.loads(reply['result']['contentItems'][0]['text']);self.assertEqual('s1',result['matches'][0]['source'])
    def test_unranked_unicode_exact_pagination_and_bounds(self):
        self.core.ingest([Event('a','observation',{},text='🙂 receipt A old'),Event('b','observation',{},text='🙂 receipt A new')])
        reader=self.reader(search_limits=SnapshotSearchLimits(max_scan_sources_per_call=1))
        first=reader.find('🙂 receipt');second=reader.find('🙂 receipt',cursor=first['next_cursor'])
        self.assertEqual(['s1','s2'],[first['matches'][0]['source'],second['matches'][0]['source']])
        self.assertEqual(0,first['matches'][0]['match_start']);self.assertFalse(reader.find('RECEIPT')['matches'])
        with self.assertRaisesRegex(WSCError,'cursor_invalid'):reader.find('x',cursor=False)
        reader=self.reader(limits=SourceAccessLimits(max_text_bytes_total=3))
        page=reader.find('receipt');self.assertFalse(page['complete']);self.assertEqual(0,page['next_cursor'])
        self.assertEqual(0,page['metrics']['rows_verified']);self.assertEqual('source_access_text_budget_exhausted',page['errors'][0]['code'])
        with self.assertRaisesRegex(WSCError,'catalog_budget'):self.reader(search_limits=SnapshotSearchLimits(max_catalog_text_bytes=1))
    def test_read_reply_budget_and_frozen_text(self):
        self.core.ingest([Event('a','observation',{},text='🙂'*5000)])
        snapshot=self.core.capture();reader=SnapshotLiteralAccess(self.core.store,snapshot,access=self.access,limits=SourceAccessLimits(max_return_bytes=2048))
        snapshot.events[0]['text']='replacement'
        page=reader.find('replacement');self.assertTrue(page['complete']);self.assertFalse(page['matches'])
        reply=reader.read('s1',limit=8192);self.assertLessEqual(len(json.dumps(reply,ensure_ascii=False,separators=(',',':')).encode()),2048)


if __name__=='__main__':unittest.main()
