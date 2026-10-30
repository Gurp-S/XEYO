from pathlib import Path
from hashlib import sha256
import copy
import json
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from blackbox import score_answer,questions,compression_evidence


class BlackboxTests(unittest.TestCase):
    def setUp(self):
        self.oracle=dict(questions=[dict(question_id='allowed',question='Is production deletion allowed?',answer_type='boolean',expected=False),
            dict(question_id='version',question='What source version is validated?',answer_type='string',expected='v1')])
    def test_correct_typed_answer_and_reversed_constraint(self):
        value=dict(answers=[dict(question_id='allowed',value=False),dict(question_id='version',value='v1')])
        self.assertEqual(2,score_answer(json.dumps(value),self.oracle)['counts']['correct'])
        value['answers'][0]['value']=True
        self.assertEqual(1,score_answer(json.dumps(value),self.oracle)['counts']['incorrect'])
    def test_bool_not_integer_missing_not_null(self):
        result=score_answer('{"answers":[{"question_id":"allowed","value":0}]}',self.oracle)
        self.assertEqual(1,result['counts']['incorrect']);self.assertEqual(1,result['counts']['missing'])
    def test_invalid_duplicate_nonfinite_or_surplus_never_passes(self):
        for text in ('{"answers":[],"answers":[]}',
            '{"answers":[{"question_id":"allowed","value":NaN}]}',
            '{"answers":[{"question_id":"allowed","value":false},{"question_id":"allowed","value":false}]}',
            '{"answers":[],"explanation":"done"}'):
            self.assertEqual(0,score_answer(text,self.oracle)['counts']['correct'])
    def test_query_excludes_answers(self):
        query=questions(self.oracle)
        self.assertTrue(all(set(item)=={'question_id','question','answer_type'} for item in query['questions']))
    def test_fresh_import_cannot_retain_raw_fixture_or_change_bootstrap(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
        from native_blackbox_sessions import verify_material
        bootstrap=[dict(type='message',role='developer',content=[])]
        hot=[dict(type='message',role='assistant',content=[])]
        self.assertTrue(verify_material(bootstrap+hot,bootstrap,hot)['bootstrap_equal'])
        with self.assertRaisesRegex(ValueError,'import_or_bootstrap_changed'):
            verify_material(bootstrap+[dict(type='message',role='assistant',content=['raw fixture'])]+hot,bootstrap,hot)
        actual=[{**bootstrap[0],'id':'new-transport-id','internal_chat_message_metadata_passthrough':{'create_time':123}},
                {**hot[0],'id':'generated-id'}]
        self.assertTrue(verify_material(actual,bootstrap,hot)['bootstrap_equal'])
        actual[0]['content']=['changed policy']
        with self.assertRaisesRegex(ValueError,'import_or_bootstrap_changed'):
            verify_material(actual,bootstrap,hot)
    def test_campaign_closure_does_not_exhaust_small_diagnostic_or_erase_unknown(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
        from blackbox_budget import close
        snapshot=dict(study=dict(limits=dict(max_total_tokens=100,max_responses=2,max_seconds=20),tokens=30,responses=1,uncertain=False),
            arms=dict(test=dict(started=0,limits=dict(max_total_tokens=100,max_responses=2,max_seconds=20),tokens=30,responses=1)),
            inflight={},response_ids=['response'])
        original=copy.deepcopy(snapshot)
        parent=dict(remaining_limits=dict(max_total_tokens=1000,max_responses=20,max_seconds=200),historical_uncertainty=True)
        result=close(parent,snapshot,3.1)
        self.assertEqual(dict(max_total_tokens=900,max_responses=18,max_seconds=196),result['remaining_limits'])
        self.assertTrue(result['historical_uncertainty']);self.assertEqual(original,snapshot)
    def test_compaction_confirmation_ignores_encrypted_payload_but_requires_receipt_and_end(self):
        before=b'{"type":"session_meta","payload":{"id":"t"}}\n'
        receipt=dict(response_id='r',thread_id='t',turn_id='u',usage=dict(total_tokens=123))
        local=[dict(type='token_usage_record',payload=receipt),dict(type='compacted',payload=dict(
            compaction_response_id='r',latest_token_usage_record=receipt,replacement_history=[dict(type='compaction',encrypted_content='unreadable')])),
            dict(type='event_msg',payload=dict(type='task_complete',turn_id='u'))]
        after=before+''.join(json.dumps(r)+'\n' for r in local).encode()
        phase=dict(thread_id='t',completed=True,failure=None,usage_complete=True,compaction=True,
            usage_completion_evidence=dict(turn_id='u'),rollout_sha256=sha256(after).hexdigest(),
            turn_accounting=dict(before=dict(sha256=sha256(before).hexdigest(),byte_length=len(before))))
        events=[dict(method='turn/completed',params=dict(threadId='t',turn=dict(id='u',status='completed')))]
        self.assertTrue(compression_evidence(before,after,phase,events)['confirmed'])
        self.assertFalse(compression_evidence(before,after,phase,[])['confirmed'])
        missing=copy.deepcopy(local);missing.pop(1)
        wrong=before+''.join(json.dumps(r)+'\n' for r in missing).encode()
        changed={**phase,'rollout_sha256':sha256(wrong).hexdigest()}
        self.assertFalse(compression_evidence(before,wrong,changed,events)['confirmed'])
        missing=copy.deepcopy(local);missing[1]['payload']['latest_token_usage_record']={}
        wrong=before+''.join(json.dumps(r)+'\n' for r in missing).encode()
        self.assertFalse(compression_evidence(before,wrong,{**phase,'rollout_sha256':sha256(wrong).hexdigest()},events)['confirmed'])


if __name__=='__main__':unittest.main()
