from pathlib import Path
import sys
from unittest import TestCase, main

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.campaign_credits import credited_remaining


class CreditChecks(TestCase):
    def setUp(self):
        self.reference=dict(max_total_tokens=100,max_responses=10,max_seconds=10)
        self.claim=dict(claim_sha256='sealed',limits=dict(max_total_tokens=80,max_responses=8,max_seconds=8))
        self.credit=dict(claim_sha256='sealed',released=dict(max_total_tokens=20,max_responses=2,max_seconds=2))

    def test_original_claim_retained_and_credit_applied_once(self):
        self.assertEqual(dict(max_total_tokens=40,max_responses=4,max_seconds=4),
            credited_remaining(self.reference,[self.claim],[self.credit]))
        self.assertEqual(80,self.claim['limits']['max_total_tokens'])

    def test_duplicate_or_unknown_credit_rejected(self):
        for credits in ([self.credit,self.credit],[dict(self.credit,claim_sha256='other')]):
            with self.assertRaisesRegex(ValueError,'unknown_or_duplicate'):
                credited_remaining(self.reference,[self.claim],credits)

    def test_negative_unknown_or_excess_release_rejected(self):
        for value in (-1,True,None,81):
            credit=dict(self.credit,released=dict(self.credit['released'],max_total_tokens=value))
            with self.assertRaises(ValueError):
                credited_remaining(self.reference,[self.claim],[credit])

    def test_duplicate_claim_cannot_be_credited(self):
        with self.assertRaisesRegex(ValueError,'duplicate_claim'):
            credited_remaining(self.reference,[self.claim,self.claim],[self.credit])


if __name__=='__main__':main()
