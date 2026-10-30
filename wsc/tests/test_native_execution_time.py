from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_execution_time import carry


class ExecutionTimeTests(unittest.TestCase):
    def test_closed_calendar_gap_cannot_consume_execution_allowance(self):
        source=dict(remaining_limits=dict(max_seconds=13880,max_total_tokens=99,max_responses=7),old_unknowns_preserved=True)
        before=deepcopy(source)
        observed=carry(source,[1.5,10.1])
        self.assertEqual(13868,observed['remaining_limits']['max_seconds'])
        self.assertEqual(99,observed['remaining_limits']['max_total_tokens'])
        self.assertEqual(7,observed['remaining_limits']['max_responses'])
        self.assertEqual(before,source)
        self.assertTrue(observed['old_unknowns_preserved'])

    def test_invalid_or_exhausted_intervals_do_not_create_time(self):
        for value in (-1,float('nan'),float('inf'),True):
            with self.assertRaisesRegex(ValueError,'interval_invalid'):
                carry(dict(remaining_limits=dict(max_seconds=100)),[value])
        with self.assertRaisesRegex(ValueError,'exhausted'):
            carry(dict(remaining_limits=dict(max_seconds=1)),[2])


if __name__=='__main__':unittest.main()
