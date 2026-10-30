from pathlib import Path
import sys
import unittest
import json
import tempfile
from hashlib import sha256

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.final_origin import model_finals,strict_json,score_bound_final
from acceptance_matrix_v1.evidence import seal


def message(identity='model',turn='current',text='answer'):
    return dict(type='response_item',payload=dict(type='message',role='assistant',phase='final_answer',id=identity,
        content=[dict(type='output_text',text=text)],internal_chat_message_metadata_passthrough=dict(turn_id=turn)))


class FinalOriginChecks(unittest.TestCase):
    def phase(self,events):return dict(usage_completion_evidence={'turn_id':'current'},finals=events)
    def final(self,identity,text):return dict(id=identity,type='agentMessage',phase='final_answer',text=text)
    def test_question_display_is_excluded_by_source_type_not_id_prefix(self):
        rows=[dict(type='response_item',payload=dict(type='function_call',name='request_user_input_async',call_id='not-a-prefix',
            internal_chat_message_metadata_passthrough={'turn_id':'current'})),message(identity='call_real_model')]
        finals,excluded=model_finals(self.phase([self.final('not-a-prefix','question'),self.final('call_real_model','answer')]),rows)
        self.assertEqual(['call_real_model'],[f['id'] for f in finals]);self.assertEqual(['not-a-prefix'],excluded)
    def test_historical_final_is_not_current(self):
        finals,_=model_finals(self.phase([self.final('new','answer')]),[message('old','previous'),message('new')])
        self.assertEqual(['new'],[f['id'] for f in finals])
    def test_genuine_multiple_finals_remain_multiple(self):
        finals,_=model_finals(self.phase([]),[message('one'),message('two')]);self.assertEqual(2,len(finals))
    def test_unknown_presentation_cannot_be_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,'event_unbound'):model_finals(self.phase([self.final('unbound','other')]),[message()])
    def test_text_mismatch_and_reused_identity_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'text_mismatch'):model_finals(self.phase([self.final('model','tampered')]),[message()])
        with self.assertRaisesRegex(ValueError,'identity_ambiguous'):model_finals(self.phase([]),[message(),message()])
    def test_model_message_without_own_turn_binding_is_unassessable(self):
        item=message();item['payload'].pop('internal_chat_message_metadata_passthrough')
        with self.assertRaisesRegex(ValueError,'turn_unbound'):
            model_finals(self.phase([]),[dict(type='turn_context',payload={'turn_id':'current'}),item])
    def test_corrupt_json_rejected(self):
        for text in ['{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}']:
            with self.assertRaises(ValueError):strict_json(text)
    def score(self,text,*,mutate=False):
        data={'policy':{'revision':2,'flag':True}}
        oracle={'expected_assertions':data['policy'],'sources':{'s':{'data':data,'sha256':seal(data)}}}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'rollout.jsonl';raw=(json.dumps(message(text=text))+'\n').encode();path.write_bytes(raw)
            phase=self.phase([self.final('model',text)]);phase['rollout_sha256']=sha256(raw).hexdigest()
            if mutate:path.write_bytes(raw+b'{}\n')
            return score_bound_final(phase,oracle,path)
    def test_annotations_not_semantically_judged_and_unknown_not_counted_wrong(self):
        text=json.dumps({'assertions':[
            dict(id='revision',value=2,source_id='s',field_path='policy.revision',status='extra annotation'),
            dict(id='flag',value=None,source_id=None,field_path=None,status='unknown')]})
        result=self.score(text)
        self.assertTrue(result['format_correct']);self.assertEqual(['flag'],result['declared_unknown_assertions'])
        self.assertEqual(0,result['nonmatching_exact_values']);self.assertEqual(0.5,result['exact_required_recall'])
        self.assertEqual(0.5,result['answerable_field_coverage'])
        self.assertIsNone(next(r for r in result['details'] if r['assertion_id']=='flag')['answer_correct'])
    def test_unstructured_or_duplicate_answer_is_not_semantically_scored(self):
        for text in ['free text answer','{"assertions":[],"assertions":[]}']:
            result=self.score(text)
            self.assertFalse(result['format_correct']);self.assertEqual(1,result['final_answer_count'])
            self.assertIsNone(result['exact_answer_correct']);self.assertIsNone(result['exact_answer_accuracy'])
    def test_changed_rollout_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'rollout_changed'):self.score('{"assertions":[]}',mutate=True)


if __name__=='__main__':unittest.main()
