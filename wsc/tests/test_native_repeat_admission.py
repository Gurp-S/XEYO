from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_repeat_admission import decide


class RepeatAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.results={arm:dict(inference_started=True,pins_unchanged=True,cleanup=dict(empty_confirmed=True)) for arm in ('B','C')}
        self.phases={arm:dict(retry_notices=[]) for arm in ('B','C')}
        self.ledger=dict(inflight={},study=dict(uncertain=False))

    def test_functional_failure_remains_sample_and_does_not_stop_known_healthy_service(self):
        self.results['C']['qualification_passed']=False
        self.assertTrue(decide(self.results,self.phases,self.ledger)['admitted'])

    def test_disconnect_and_quota_stop_before_next_repetition(self):
        for info in ({'responseStreamDisconnected':{'httpStatusCode':None}},'usageLimitExceeded'):
            self.phases['C']['retry_notices']=[dict(error=dict(codexErrorInfo=info))]
            outcome=decide(self.results,self.phases,self.ledger)
            self.assertFalse(outcome['admitted'])
            self.assertIn('provider_unavailable:C',outcome['reasons'])

    def test_unknown_usage_and_live_cleanup_cannot_be_reclassified_by_new_envelope(self):
        self.ledger['study']['uncertain']=True
        self.results['B']['cleanup']['empty_confirmed']=False
        self.assertFalse(decide(self.results,self.phases,self.ledger)['admitted'])

    def test_decision_does_not_mutate_historical_accounting(self):
        before=deepcopy((self.results,self.phases,self.ledger))
        decide(self.results,self.phases,self.ledger)
        self.assertEqual(before,(self.results,self.phases,self.ledger))


if __name__=='__main__':unittest.main()
