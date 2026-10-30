from pathlib import Path
import sys,json,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'validation'),str(ROOT/'benchmarks/deterministic_v1')]
from structured_tool_outputs import decoded_transport_objects


class StructuredToolOutputsTests(unittest.TestCase):
    def test_double_encoded_round_trip(self):
        value={'text':'quote " and slash \\','version':False,'count':0,'other':None}
        payload=[{'type':'input_text','text':json.dumps(json.dumps(value))}]
        self.assertIn(value,list(decoded_transport_objects(payload)))

    def test_inversion_and_wrong_values_not_repaired(self):
        wrong={'allow':False,'revision':1}
        values=list(decoded_transport_objects(json.dumps(json.dumps(wrong))))
        self.assertIn(wrong,values)
        self.assertNotIn({'allow':True,'revision':2},values)

    def test_malformed_string_not_unescaped_by_guessing(self):
        self.assertEqual([],list(decoded_transport_objects('"{\\"allow\\":true}')))


if __name__=='__main__':unittest.main()
