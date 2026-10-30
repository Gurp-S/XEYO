from pathlib import Path
from copy import deepcopy
import sys,unittest,random
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_metadata_columns import project,restore,vector,expand,MAX_ROWS
from wsc.contracts import encode,digest


class MetadataColumnTests(unittest.TestCase):
    def test_vectors_typed_and_random(self):
        rng=random.Random(20261027)
        cases=[[],[False,0,None,True,1]*30,list(range(-30,100)),['id'+str(i) for i in range(90)],
            [{'manifest_key':'item'+str(i)} for i in range(90)],['01','02','10']*20,
            [rng.choice([False,0,None,'中文',3.5]) for _ in range(200)]]
        for case in cases:
            with self.subTest(case=str(case)[:50]):self.assertEqual(encode(expand(vector(case),len(case))),encode(case))

    def test_round_trip_targets_only(self):
        material={'events':{'format':'wsc.cold_event_rows/1','rows':[[i,{'manifest_key':'x'+str(i)},'x'+str(i),i%2==0] for i in range(100)]},
            'selection_facts':{'source_record_table':{'columns':['source','size'],'rows':[['x'+str(i),123] for i in range(100)]}},
            'previous_excerpts':[{'text':'keep this exact arbitrary prose','scope':None}]}
        result,binding=project(material)
        self.assertEqual(len(binding['paths']),2);self.assertLess(len(encode(result)),len(encode(material)))
        self.assertEqual(encode(restore(result,binding)),encode(material))
        self.assertEqual(result['previous_excerpts'],material['previous_excerpts'])
        changed=deepcopy(result);changed['events']['rows']['row_count']+=1
        with self.assertRaisesRegex(Exception,'binding_changed'):restore(changed,binding)

    def test_malformed_encodings_rejected(self):
        invalid=[({'encoding':'runs','runs':[['x',True]]},1),({'encoding':'dictionary','dictionary':['x'],'indices':[True]},1),
            ({'encoding':'integer_progression','start':False,'step':1},2),({'encoding':'values','values':[]},1),
            ({'encoding':'values','values':[]},MAX_ROWS+1)]
        for value,count in invalid:
            with self.subTest(value=value):
                with self.assertRaises(Exception):expand(value,count)

    def test_small_or_heterogeneous_passthrough(self):
        material={'events':[],'selection_facts':{'source_record_table':{'columns':['x'],'rows':[[False],[]]}},'text':'opaque'}
        result,binding=project(material);self.assertEqual(result,material);self.assertEqual(binding['paths'],[])


if __name__=='__main__':unittest.main()
