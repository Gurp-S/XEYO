from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.campaign_allocation import remaining


class AllocationChecks(unittest.TestCase):
    def test_whole_first_allocation_withheld_including_unknown_and_unused(self):
        original=dict(max_total_tokens=17771795,max_responses=272,max_seconds=11095)
        first=dict(max_total_tokens=2000000,max_responses=64,max_seconds=3600)
        second=dict(max_total_tokens=2000000,max_responses=64,max_seconds=2400)
        self.assertEqual(dict(max_total_tokens=13771795,max_responses=144,max_seconds=5095),remaining(original,[first,second]))
        self.assertEqual(17771795,original['max_total_tokens'])
    def test_overallocated_reference_rejected(self):
        value=dict(max_total_tokens=1,max_responses=1,max_seconds=1)
        with self.assertRaisesRegex(ValueError,'allocation_exceeds_reference'):remaining(value,[value,value])
    def test_unknown_or_negative_cannot_be_zero_filled(self):
        for tokens in (None,-1,True):
            with self.assertRaises(ValueError):remaining(dict(max_total_tokens=tokens,max_responses=1,max_seconds=1),[])


if __name__=='__main__':unittest.main()
