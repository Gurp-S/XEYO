from pathlib import Path
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Selection,Limits
from wsc.contracts import Event,encode,WSCError
from wsc.selection_facts import describe as legacy
from wsc.projected_selection_facts import describe,admit
from wsc.source_reference_view import MODE
from wsc.view_budget import admit_generation
from wsc.span_selection import span_material
from native_incremental_candidate import frontier


class ProjectedSelectionFactsTests(unittest.TestCase):
    def test_measured_records_and_empty_body_match_actual_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);core=WSC(Store(root/'s.db',session_id='s',workspace=tmp),access=lambda *a:True)
            core.ingest([Event('u','message',{'role':'user'},role='user',text='constraint'),
                Event('e','observation',{'large':'x'*60000},text='small public text')])
            snap=core.capture();old=legacy(snap.events,131072);new=describe(snap.events,131072)
            bodies=[]
            for selection in (Selection(),Selection(source_ids=('e','e'))):
                view=core.prepare(snap,selection,producer='test',source_projection=MODE)
                with core.store.connect() as db:bodies.append(json.loads(db.execute('SELECT data FROM views WHERE id=?',(view,)).fetchone()[0])['body'])
            self.assertEqual(new['mandatory_empty_view_bytes'],len(encode(bodies[0]).encode()))
            self.assertNotEqual(old['mandatory_empty_view_bytes'],len(encode(bodies[0]).encode()))
            row=next(r for r in bodies[1]['sources'] if r['id']=='e')
            self.assertEqual(new['source_records']['e']['serialized_record_bytes'],len(encode(row).encode()))
            self.assertGreater(old['source_records']['e']['serialized_record_bytes']-new['source_records']['e']['serialized_record_bytes'],59000)
            self.assertEqual(new['mandatory_empty_view_bytes']+1+new['source_records']['e']['serialized_record_bytes'],len(encode(bodies[1]).encode()))
            # Exact control-only boundary: metadata is not free.
            cap=new['mandatory_empty_view_bytes']-1
            with self.assertRaisesRegex(WSCError,'mandatory_view_byte_budget_exhausted'):admit(snap.events,cap)
            with self.assertRaisesRegex(WSCError,'view_byte_budget_exhausted'):core.prepare(snap,Selection(),producer='test',source_projection=MODE,limits=Limits(max_view_bytes=cap))
            offered=span_material({**core.material(snap),'selection_facts':new})
            self.assertEqual(offered['selection_facts']['selection_effects']['source_ids'],new['selection_effects']['source_ids'])
            self.assertNotIn('x'*1000,encode(offered))
            _,default=frontier(core,snap,None,root/'cold')
            _,fixed=frontier(core,snap,None,root/'cold',projection_facts=True)
            self.assertEqual(default['selection_facts']['schema'],'wsc.selection_facts/1')
            self.assertEqual(fixed['selection_facts']['mandatory_empty_view_bytes'],new['mandatory_empty_view_bytes'])
            self.assertEqual(default['events'],fixed['events'])
            self.assertTrue(fixed['selection_facts']['source_records']['s1']['automatically_retained'])

    def test_large_control_payload_reference_is_not_false_budget_denial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);core=WSC(Store(root/'s.db',session_id='s',workspace=tmp),access=lambda *a:True)
            core.ingest([Event('control','observation',{'large':'x'*200000},control=True,text='constraint')])
            snap=core.capture();facts=describe(snap.events,1000)
            with self.assertRaisesRegex(WSCError,'mandatory_view_byte_budget_exhausted'):admit_generation(snap.events,1000)
            admit(snap.events,1000)
            core.prepare(snap,Selection(),producer='test',source_projection=MODE,limits=Limits(max_view_bytes=1000))
            self.assertLess(facts['mandatory_empty_view_bytes'],1000)

    def test_opaque_mandatory_and_unknown_projection_still_rejected(self):
        prefix=[dict(id='x',kind='opaque',payload={},text=None,role=None,control=True)]
        with self.assertRaisesRegex(WSCError,'opaque_hot_selection_unavailable'):admit(prefix,1000)
        with self.assertRaisesRegex(WSCError,'view_source_projection_unsupported'):describe([],1000,mode='unknown')


if __name__=='__main__':unittest.main()
