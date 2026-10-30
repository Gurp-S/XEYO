from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import sys,tempfile,unittest,json,random
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Event,WSCError
from wsc.contracts import encode
from wsc.source_access import SourceAccessLimits
from wsc.snapshot_literal_access import SnapshotLiteralAccess
from native_deferred_catalog import project,restore
from native_catalog_tool import CatalogAccess,CatalogToolHandler


def material(snapshot):
    return dict(session_id=snapshot.session_id,frontier_boundary=dict(current_cut=snapshot.cut,source_digest=snapshot.source_digest),
        events=[dict(id='s'+str(r['seq']),seq=r['seq'],kind=r['kind'],role=r['role'],text_in_frontier=False,public_text_available=False,spans=[],cold_source={'manifest_key':'s'+str(r['seq'])}) for r in snapshot.events],
        selection_facts=dict(source_record_table=dict(columns=['source','automatically_retained','serialized_record_bytes','public_text_utf8_bytes'],rows=[['s'+str(r['seq']),r['control'],123,len(r['text'])] for r in snapshot.events])),
        previous_excerpts=[dict(text='原文保持',scope=None)],understandings=[])


class DeferredCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.allowed=True
        root=Path(self.tmp.name);self.core=WSC(Store(root/'s.db',session_id='s',workspace=str(root)),access=lambda *a:self.allowed)
        self.core.ingest([Event(str(i),'observation',{'value':i},text='original '+str(i)) for i in range(20)])
        self.snapshot=self.core.capture();self.original=material(self.snapshot)
    def handler(self,**kwargs):return CatalogToolHandler(CatalogAccess(self.core.store,self.snapshot,access=self.core.access,**kwargs))
    def event(self,operation='catalog',call='c'):
        return dict(id=call,method='item/tool/call',params=dict(threadId='t',turnId='u',callId=call,tool='WSCSource',arguments={'operation':operation}))
    def test_full_restore_hot_fields_and_bounded_reply(self):
        self.original['events'][-1].update(text_in_frontier=True,public_text_available=True,spans=[{'ref':'p1','text':'原文'}])
        handler=self.handler();wire,payload,binding=handler.project_material(self.original)
        self.assertTrue(binding['applied']);self.assertEqual(len(wire['events']),1)
        self.assertEqual(wire['events'][0],self.original['events'][-1]);self.assertEqual(wire['previous_excerpts'],self.original['previous_excerpts'])
        response=handler.handle(self.event(),thread_id='t',turn_id='u');value=json.loads(response['result']['contentItems'][0]['text'])
        self.assertTrue(response['result']['success']);self.assertLessEqual(len(encode(value).encode()),16384)
        self.assertEqual(encode(restore(wire,value['catalog'],binding)),encode(self.original))
        self.assertEqual(value['metrics']['metadata_sources_checked'],20);self.assertEqual(handler.reader.rows_verified,0)
        self.assertEqual(response,handler.handle(self.event(),thread_id='t',turn_id='u'));self.assertEqual(handler.reader.calls,1)
    def test_permission_revocation_and_shared_call_limit(self):
        handler=self.handler(limits=SourceAccessLimits(max_calls=1));handler.project_material(self.original);self.allowed=False
        response=handler.handle(self.event(),thread_id='t',turn_id='u')
        self.assertFalse(response['result']['success']);self.assertNotIn('catalog_sha256',response['result']['contentItems'][0]['text'])
        read=self.event('read','next');read['params']['arguments']['source']='s1'
        denied=handler.handle(read,thread_id='t',turn_id='u');self.assertFalse(denied['result']['success'])
        self.assertIn('callback_budget_exhausted',denied['result']['contentItems'][0]['text']);self.assertEqual(handler.reader.rows_verified,0)
    def test_snapshot_metadata_is_not_live_health_and_reads_still_validate(self):
        handler=self.handler();handler.project_material(self.original)
        with self.core.store.transaction() as db:db.execute("UPDATE events SET data='{}' WHERE id='0'")
        reply=handler.reader.catalog_read();self.assertIn('not_performed',reply['storage_validation'])
        with self.assertRaisesRegex(WSCError,'integrity'):handler.reader.read('s1')
    def test_cross_turn_bad_parameters_and_corrupt_binding(self):
        handler=self.handler();wire,payload,binding=handler.project_material(self.original)
        with self.assertRaisesRegex(WSCError,'binding_invalid'):handler.handle(self.event(),thread_id='t',turn_id='other')
        self.assertEqual(handler.reader.calls,0)
        event=self.event();event['params']['arguments']['source']='s1'
        self.assertFalse(handler.handle(event,thread_id='t',turn_id='u')['result']['success']);self.assertEqual(handler.reader.calls,0)
        changed=deepcopy(payload);changed['source_count']+=1
        with self.assertRaisesRegex(WSCError,'catalog_changed'):restore(wire,changed,binding)
    def test_fallback_for_result_and_scan_limits(self):
        wire,payload,binding=project(self.original,max_return_bytes=100)
        self.assertFalse(binding['applied']);self.assertIsNone(payload);self.assertEqual(wire,self.original)
        wire,payload,binding=project(self.original,max_sources=2)
        self.assertFalse(binding['applied']);self.assertEqual(wire,self.original)
    def test_read_without_catalog_is_unchanged(self):
        old=SnapshotLiteralAccess(self.core.store,self.snapshot,access=self.core.access);new=self.handler().reader
        self.assertEqual(old.read('s1'),new.read('s1'))
    def test_metadata_scan_above_live_row_quota_is_explicit_not_live_validation(self):
        self.core.ingest([Event('extra'+str(i),'observation',{},text='receipt') for i in range(580)])
        snapshot=self.core.capture();reader=CatalogAccess(self.core.store,snapshot,access=self.core.access);handler=CatalogToolHandler(reader)
        handler.project_material(material(snapshot));result=reader.catalog_read()
        self.assertEqual(result['metrics']['metadata_sources_checked'],600)
        self.assertEqual(reader.rows_verified,0);self.assertEqual(reader.calls,1)
        reader.read('s1');self.assertEqual(reader.rows_verified,1);self.assertEqual(reader.calls,2)
    def test_wrong_snapshot_and_nonempty_cold_spans_cannot_be_hidden(self):
        wrong=deepcopy(self.original);wrong['session_id']='other';_,payload,binding=project(wrong)
        with self.assertRaisesRegex(WSCError,'snapshot_binding_changed'):self.handler().install_catalog(payload,binding)
        visible=deepcopy(self.original);visible['events'][0]['spans']=[{'ref':'p','text':'完整文本'}]
        wire,payload,binding=project(visible)
        self.assertIn(visible['events'][0],wire['events'])
        self.assertEqual(encode(restore(wire,payload,binding)),encode(visible))
    def test_catalog_deadline_is_result_error(self):
        handler=self.handler();handler.project_material(self.original)
        with patch('native_catalog_tool.monotonic',side_effect=[0,100]):
            result=handler.handle(self.event(),thread_id='t',turn_id='u')
        self.assertFalse(result['result']['success']);self.assertIn('deadline_exhausted',result['result']['contentItems'][0]['text'])


if __name__=='__main__':unittest.main()
