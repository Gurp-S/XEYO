from pathlib import Path
import sys,tempfile,unittest,copy
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'experiments'),str(Path(__file__).resolve().parents[1]/'src')]
from native_selection_wire import project,restore,normalize_draft,transport_value,transport_equal
from native_incremental_generation import output_schema
from wsc import WSCError


class SelectionWireTests(unittest.TestCase):
    def test_previous_typed_references_use_one_namespace_without_rewriting_text(self):
        with tempfile.TemporaryDirectory() as directory:
            original=self.offered()
            original['previous_selection']={'source_ids':['long-source-identity'],'clues':[{'text':'literal long-source-identity','sources':['long-source-identity']}]}
            original['previous_excerpts']=[{'source_id':'long-source-identity','text':'old literal','key':'unchanged-key'}]
            wire,manifest,binding=project(original,Path(directory)/'manifest.json')
            self.assertEqual(['s1'],wire['previous_selection']['source_ids'])
            self.assertEqual(['s1'],wire['previous_selection']['clues'][0]['sources'])
            self.assertEqual('s1',wire['previous_excerpts'][0]['source_id'])
            self.assertEqual('literal long-source-identity',wire['previous_selection']['clues'][0]['text'])
            self.assertEqual(original,restore(wire,manifest,binding))
    def test_json_transport_path_tuple_is_not_a_source_change(self):
        original={'previous_excerpts':[{'path':(),'source_id':'s1'}],'flag':False,'revision':10**30}
        normalized=transport_value(original)
        self.assertEqual([],normalized['previous_excerpts'][0]['path'])
        self.assertEqual((),original['previous_excerpts'][0]['path'])
        self.assertEqual(original['revision'],normalized['revision'])
        self.assertIs(normalized['flag'],False)
        self.assertTrue(transport_equal(original,normalized))
        wrong_type=copy.deepcopy(normalized);wrong_type['flag']=0
        self.assertFalse(transport_equal(normalized,wrong_type))
        changed=copy.deepcopy(normalized);changed['previous_excerpts'][0]['source_id']='s2'
        self.assertNotEqual(normalized,changed)
        with self.assertRaises(ValueError):transport_value({'bad':float('nan')})
    def offered(self):
        return dict(events=[dict(id='s1',seq=1,kind='message',role='user',call_id=None,observed_at=None,
            text_in_frontier=True,public_text_available=True,public_text_characters=4,
            spans=[dict(ref='p0',text='禁止🙂删')],cold_source=dict(path='D:/evidence/one.json',sha256='a'*64,source_id='long-source-identity',observed_at=None))],
            understandings=[dict(text='possibly obsolete',kind='hypothesis',sources=['s1'],scope=None)],
            selection_facts=dict(source_records={'s1':dict(automatically_retained=True,serialized_record_bytes=400,public_text_utf8_bytes=13)}))
    def test_roundtrip_preserves_text_nulls_facts_and_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            original=self.offered();saved=copy.deepcopy(original)
            wire,manifest,binding=project(original,Path(directory)/'manifest.json')
            self.assertEqual(saved,original);self.assertEqual(original,restore(wire,manifest,binding))
            self.assertEqual(original['events'][0]['spans'],wire['events'][0]['spans'])
            self.assertTrue(wire['selection_facts']['source_record_table']['rows'][0][1])
            self.assertEqual(original['understandings'],wire['understandings'])
            for target in ('wire','manifest'):
                w=copy.deepcopy(wire);m=copy.deepcopy(manifest)
                if target=='wire':w['events'][0]['spans'][0]['text']='允许删除'
                else:m['cold_sources']['s1']['sha256']='b'*64
                with self.assertRaisesRegex(WSCError,'binding_changed'):restore(w,m,binding)
    def test_alias_only_rewrites_typed_source_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            offered=self.offered();_,_,binding=project(offered,Path(directory)/'manifest.json')
            draft=dict(source_ids=['long-source-identity'],new_understandings=[dict(text='literal long-source-identity',sources=['long-source-identity'],scope={'note':'long-source-identity'},expected_revision=None)])
            result=normalize_draft(draft,binding)
            self.assertEqual(['s1'],result['source_ids']);self.assertEqual(['s1'],result['new_understandings'][0]['sources'])
            self.assertEqual('literal long-source-identity',result['new_understandings'][0]['text'])
            self.assertEqual(draft['new_understandings'][0]['scope'],result['new_understandings'][0]['scope'])
            with self.assertRaisesRegex(WSCError,'not_offered'):normalize_draft(dict(source_ids=['absent']),binding)
            schema=output_schema({**offered,'understandings':[],'previous_excerpts':[]},source_aliases_only=True)
            self.assertEqual(['s1'],schema['$defs']['source_refs']['items']['enum'])
    def test_missing_unknown_and_false_are_not_merged(self):
        with tempfile.TemporaryDirectory() as directory:
            offered=self.offered();second=copy.deepcopy(offered['events'][0]);second.update(id='s2',observed_at='later',text_in_frontier=False)
            second['cold_source']['source_id']='source-two';second.pop('call_id');offered['events'].append(second)
            wire,manifest,binding=project(offered,Path(directory)/'manifest.json')
            self.assertNotIn('call_id',wire['event_defaults'])
            self.assertEqual(offered,restore(wire,manifest,binding))


if __name__=='__main__':unittest.main()
