from pathlib import Path
import sys
from unittest import TestCase, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.phase_timing import PhaseTiming, union_seconds


class TimingChecks(TestCase):
    def test_nested_intervals_are_not_double_counted(self):
        now = [0.]
        trace = PhaseTiming(clock=lambda:now[0], cpu_clock=lambda:now[0])
        with trace.measure('chain'):
            now[0] = 1.
            with trace.measure('provider_http'):
                now[0] = 4.
            now[0] = 5.
        value = trace.snapshot()
        self.assertTrue(value['complete'])
        self.assertEqual(5., value['measured_interval_union_seconds'])
        self.assertEqual(2., value['components']['chain']['exclusive_wall_seconds'])
        self.assertEqual(3., value['components']['provider_http']['inclusive_wall_seconds'])

    def test_exceptions_propagate_and_active_trace_is_incomplete(self):
        trace = PhaseTiming()
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with trace.measure('persist'):
                self.assertFalse(trace.snapshot()['complete'])
                raise RuntimeError('fixture')
        self.assertTrue(trace.snapshot()['complete'])
        self.assertEqual(1, trace.snapshot()['components']['persist']['errors'])
        self.assertNotIn('fixture', str(trace.snapshot()))

    def test_overlap_union_and_reversed_clock(self):
        self.assertEqual(6, union_seconds([(0,3),(2,5),(8,9)]))
        with self.assertRaisesRegex(ValueError, 'clock_reversed'):
            union_seconds([(2,1)])

    def test_call_preserves_result_identity(self):
        trace = PhaseTiming()
        result = object()
        self.assertIs(result, trace.call('read', lambda:result))
        self.assertEqual('success', trace.snapshot()['spans'][0]['outcome'])


if __name__ == '__main__':
    main()
