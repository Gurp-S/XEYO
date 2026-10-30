from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_campaign_envelope import qualification_envelope
from native_application_budget_policy import shared_arm_allocation


class CampaignEnvelopeTests(unittest.TestCase):
    def history(self):
        return dict(inflight={},study=dict(tokens=20,responses=2,uncertain=True,
            limits=dict(max_total_tokens=1000,max_responses=100,max_seconds=100)),
            arms=dict(old=dict(started=0,tokens=20,responses=2,
                limits=dict(max_total_tokens=100,max_responses=10,max_seconds=20))),
            response_ids=['old1','old2'])

    def test_known_and_unknown_allocations_are_both_withheld(self):
        old=self.history()
        unchanged=deepcopy(old)
        proto=dict(usage_complete=True,receipts=dict(response_receipts=[dict(response_id='proto',usage=dict(total_tokens=5))]))
        result=qualification_envelope(old,[proto],10.1)
        self.assertEqual(result['remaining_limits'],dict(max_total_tokens=895,max_responses=89,max_seconds=89))
        self.assertEqual(result['withheld_unused_arm_allocation'],dict(tokens=80,responses=8))
        self.assertIsNone(result['historical_complete_usage'])
        self.assertFalse(result['total_campaign_usage_complete'])
        self.assertEqual(old,unchanged)

    def test_open_history_and_reused_response_cannot_be_admitted(self):
        old=self.history()
        old['inflight']={'pending':{}}
        with self.assertRaisesRegex(ValueError,'not_closed'):
            qualification_envelope(old,[],1)
        old['inflight']={}
        phase=dict(usage_complete=True,receipts=dict(response_receipts=[dict(response_id='old1',usage=dict(total_tokens=1))]))
        with self.assertRaisesRegex(ValueError,'reused'):
            qualification_envelope(old,[phase],1)

    def test_response_overshoot_is_never_reduced_to_original_allocation(self):
        old=self.history()
        old['arms']['old']['tokens']=120
        old['study']['tokens']=120
        result=qualification_envelope(old,[],1)
        self.assertEqual(result['remaining_limits']['max_total_tokens'],880)
        self.assertEqual(result['withheld_unused_arm_allocation']['tokens'],0)

    def test_shared_phase_allocation_preserves_global_and_arm_caps(self):
        budgets={name:dict(max_total_tokens=amount,max_responses=10,max_seconds=20)
            for name,amount in [('ordinary_phase',75),('boundary_phase',40),('per_arm',600),('study',18000)]}
        budgets['per_arm']['max_responses']=120
        old=deepcopy(budgets)
        result=shared_arm_allocation(budgets)
        self.assertEqual(result['ordinary_phase']['max_total_tokens'],600)
        self.assertEqual(result['ordinary_phase']['max_responses'],120)
        for key in ('boundary_phase','per_arm','study'):
            self.assertEqual(result[key],old[key])
        self.assertEqual(budgets,old)


if __name__=='__main__':
    unittest.main()
