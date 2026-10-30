from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_live_context_trial import LiveContextTrial,TARGET_INDEX


class Ledger:
    def remaining(self,ticket): return {}
    def settle(self,ticket,outcome): return dict(known_total_tokens=sum(r['usage']['total_tokens'] for r in outcome['receipts']['response_receipts']))
    def finish(self,*args): pass


class TrialChecks(TestCase):
    def test_public_pointer_and_oracle_address_same_record(self):
        t=LiveContextTrial()
        source=json.loads(t.text)
        self.assertEqual(t.target['coordinates'],'RFC6901_zero_based_array_index')
        self.assertEqual(t.target['pointer'],f'/records/{TARGET_INDEX}/token')
        self.assertIn(t.target['pointer'],t.request)
        self.assertIn('索引从0计数',t.request)
        self.assertEqual(source['records'][TARGET_INDEX]['token'],t.nonce)
        self.assertNotEqual(source['records'][TARGET_INDEX-1]['token'],t.nonce)

    def trial(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        t=LiveContextTrial.__new__(LiveContextTrial)
        t.private=Path(temp.name);t.reference='result:r1';t.nonce='expected-nonce'
        t.receipts=[];t.messages=[];t.network_attempts=0;t.settled=False
        t.ledger=Ledger();t.ticket={'ticket':'fixture'}
        t.provider=SimpleNamespace(trace=[])
        return t

    def answer(self,t,*,nonce=None,reference=None):
        t.messages=[dict(role='assistant',type='message',content=[dict(type='output_text',text=json.dumps(
            dict(answer=nonce or t.nonce,reference=reference or t.reference)))])]
        t.network_attempts=1;t.receipts=[dict(response_id='r',usage=dict(input_tokens=10,output_tokens=2,total_tokens=12))]

    def test_correct_answer_with_actual_query_and_complete_usage(self):
        t=self.trial();self.answer(t);result=t.finish([{'actual_query':True}])
        self.assertTrue(result['success']);self.assertEqual(result['settlement']['known_total_tokens'],12)

    def test_answer_without_query_not_recovery_proof(self):
        t=self.trial();self.answer(t);self.assertFalse(t.finish([])['success'])

    def test_wrong_value_or_reference_rejected(self):
        for args in ({'nonce':'wrong'},{'reference':'result:r2'}):
            t=self.trial();self.answer(t,**args)
            self.assertFalse(t.finish([{}])['exact_answer_and_reference'])

    def test_unknown_receipt_prevents_next_network_attempt(self):
        t=self.trial();t.network_attempts=1
        with self.assertRaisesRegex(ValueError,'prior_response_unknown'):t.exchange(b'{}')
        self.assertEqual(t.network_attempts,1)
        result=t.finish([],failure='interrupted')
        self.assertFalse(result['usage_complete']);self.assertFalse(result['success'])


if __name__=='__main__':main()
