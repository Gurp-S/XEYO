from pathlib import Path
import sys
import json
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.final_assertions import score_final
from acceptance_matrix_v1.evidence import seal


class FinalChecks(unittest.TestCase):
    def setUp(self):
        data={'allow':False}
        self.oracle=dict(expected_assertions={'guard':False},sources={'source':dict(data=data,sha256=seal(data))})
    def phase(self,value):
        return dict(finals=[dict(type='agentMessage',phase='final_answer',text=value)])
    def test_exact_json_field(self):
        value={'assertions':[dict(assertion_id='guard',value=False,source_id='source',field_path=['allow'])]}
        result=score_final(self.phase(json.dumps(value)),self.oracle)
        self.assertEqual(1,result['exact_answer_correct']);self.assertEqual(1,result['citation_byte_matches'])
    def test_reversed_constraint_is_not_correct(self):
        value={'assertions':[dict(assertion_id='guard',value=True,source_id='source',field_path=['allow'])]}
        result=score_final(self.phase(json.dumps(value)),self.oracle)
        self.assertEqual(0,result['exact_answer_correct']);self.assertEqual(0,result['citation_byte_matches'])
    def test_prose_is_not_inferred_by_keyword(self):
        result=score_final(self.phase('source allow false guard'),self.oracle)
        self.assertEqual(0,result['submitted_assertions']);self.assertIsNotNone(result['output_parse_error'])
    def test_identifier_alias_and_dot_path_are_exact_fields(self):
        value={'assertions':[dict(id='guard',value=False,source_id='source',field_path='allow')]}
        self.assertEqual(1,score_final(self.phase(json.dumps(value)),self.oracle)['citation_byte_matches'])
    def test_nested_dot_path_has_exact_source_field(self):
        data={'nested':{'allow':False}}
        oracle=dict(expected_assertions={'guard':False},sources={'source':dict(data=data,sha256=seal(data))})
        value={'assertions':[dict(id='guard',value=False,source_id='source',field_path='nested.allow')]}
        self.assertEqual(1,score_final(self.phase(json.dumps(value)),oracle)['citation_byte_matches'])
    def test_ambiguous_literal_dot_is_not_guessed(self):
        data={'nested':{'allow':False},'nested.allow':True}
        oracle=dict(expected_assertions={'guard':False},sources={'source':dict(data=data,sha256=seal(data))})
        value={'assertions':[dict(id='guard',value=False,source_id='source',field_path='nested.allow')]}
        result=score_final(self.phase(json.dumps(value)),oracle)
        self.assertEqual('dot_path_ambiguous',result['output_parse_error'])
        self.assertEqual(0,result['citation_byte_matches'])


if __name__=='__main__':unittest.main()
