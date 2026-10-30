from pathlib import Path
import sys,tempfile,unittest,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc import WSC,Store,Event,WSCError
from wsc.source_access import SnapshotSourceAccess,SourceAccessLimits


class SourceAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.allowed=True;self.access=lambda *a:self.allowed
        self.core=WSC(Store(self.root/'state.db',session_id='s',workspace=str(self.root)),access=self.access)
        self.core.ingest([Event('old','observation',{},text='receipt A, value=old'),Event('new','observation',{},text='receipt A, value=new'),Event('unicode','observation',{},text='🙂'*5000)])
        self.snapshot=self.core.capture()
    def test_literal_is_unranked_and_does_not_override_old_state(self):
        reader=SnapshotSourceAccess(self.core.store,self.snapshot,access=self.access)
        result=reader.find('receipt A');self.assertTrue(result['complete'])
        self.assertEqual(['s1','s2'],[m['source'] for m in result['matches']])
        self.assertEqual('receipt A, value=old',reader.read('old')['text'])
        self.assertEqual('receipt A, value=new',reader.read('s2')['text'])
        self.assertEqual([],reader.find('RECEIPT A')['matches'])
    def test_pagination_and_errors_are_not_a_negative_match(self):
        reader=SnapshotSourceAccess(self.core.store,self.snapshot,access=self.access,limits=SourceAccessLimits(max_rows_per_call=1))
        first=reader.find('receipt A');self.assertFalse(first['complete']);self.assertEqual(1,first['next_cursor'])
        self.assertEqual({'start_cursor':0,'end_cursor':1,'total_sources':3},first['coverage'])
        self.assertEqual('s2',reader.find('receipt A',cursor=first['next_cursor'])['matches'][0]['source'])
        self.allowed=False
        denied=reader.find('receipt A');self.assertFalse(denied['complete']);self.assertTrue(denied['errors'])
        with self.assertRaisesRegex(WSCError,'Permission denied'):reader.read('s1')
    def test_source_seal_and_utf8_return_budget(self):
        reader=SnapshotSourceAccess(self.core.store,self.snapshot,access=self.access,limits=SourceAccessLimits(max_return_bytes=2048))
        part=reader.read('s3',limit=8192);self.assertLessEqual(len(json.dumps(part,ensure_ascii=False,separators=(',',':')).encode()),2048)
        self.assertFalse(part['complete']);self.assertEqual('🙂'*(part['end']-part['offset']),part['text'])
        with self.core.store.transaction() as db:db.execute("UPDATE events SET data='{}' WHERE id='old'")
        with self.assertRaisesRegex(WSCError,'integrity'):reader.read('old')
    def test_limits_unknown_ids_and_boolean_indices(self):
        reader=SnapshotSourceAccess(self.core.store,self.snapshot,access=self.access,limits=SourceAccessLimits(max_calls=2))
        with self.assertRaisesRegex(WSCError,'not_bound'):reader.read('other')
        with self.assertRaisesRegex(WSCError,'range_invalid'):reader.read('s1',offset=False)
        with self.assertRaisesRegex(WSCError,'call_budget'):reader.read('s1')
    def test_unscanned_source_is_not_skipped_at_total_budget(self):
        reader=SnapshotSourceAccess(self.core.store,self.snapshot,access=self.access,limits=SourceAccessLimits(max_rows_total=1))
        result=reader.find('receipt')
        self.assertFalse(result['complete']);self.assertEqual(1,result['next_cursor'])
        self.assertEqual('source_access_row_budget_exhausted',result['errors'][0]['code'])


if __name__=='__main__':unittest.main()
