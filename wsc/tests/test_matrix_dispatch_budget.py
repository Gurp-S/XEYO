from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.dispatch_budget import DispatchBudget, inspect_ledger


def limits(tokens=100, responses=20, seconds=100):
    return dict(max_total_tokens=tokens, max_responses=responses, max_seconds=seconds)


def phase(identity, tokens, *, complete=True, failure=None):
    return dict(receipts=dict(response_receipts=[dict(response_id=identity, usage=dict(total_tokens=tokens))]),
                usage_complete=complete, failure=failure)


class Clock:
    value = 0.
    def __call__(self):
        return self.value


class MatrixDispatchBudgetChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'ledger.db'
        self.clock = Clock()
        self.runs = {name: dict(arm=arm, limits=limits(), binding=dict(task='T1', arm=arm,
                    repetition=index, history_sha256='fixture-sha', model='registered-model', effort='max'))
                     for index, (name, arm) in enumerate([('B1', 'Bprime'), ('C1', 'C'), ('B2', 'Bprime')])}
        self.ledger = DispatchBudget(self.path, self.runs, limits(), clock=self.clock)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_concurrent_reservations_share_global_cap_and_are_durable(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(lambda name: self.ledger.reserve(name, 'task', limits(80, 2)), ['B1', 'C1']))
        self.assertEqual(100, a['limits']['max_total_tokens']+b['limits']['max_total_tokens'])
        state = inspect_ledger(self.path)
        self.assertEqual(2, len(state['state']['tickets']))
        self.assertEqual(['registered', 'reserved', 'reserved'], [e['kind'] for e in state['events']])

    def test_run_and_phase_cannot_be_replayed(self):
        a = self.ledger.reserve('B1', 'task', limits(30, 2))
        with self.assertRaisesRegex(ValueError, 'active'):
            self.ledger.reserve('B1', 'different-phase', limits(10, 1))
        self.ledger.settle(a['ticket'], phase('response-1', 12))
        with self.assertRaisesRegex(ValueError, 'already_dispatched'):
            self.ledger.reserve('B1', 'task', limits(10, 1))
        self.ledger.finish('B1', dict(success=True))
        with self.assertRaisesRegex(ValueError, 'not_dispatchable'):
            self.ledger.reserve('B1', 'new-task', limits(10, 1))
        self.runs['B1']['binding']['model'] = 'caller-mutated-model'
        self.assertEqual('registered-model', inspect_ledger(self.path)['state']['runs']['B1']['spec']['binding']['model'])

    def test_arm_cap_counts_other_repetitions_and_held_tokens(self):
        self.ledger.arm_ceiling = 70
        first = self.ledger.reserve('B1', 'task', limits(50, 2))
        second = self.ledger.reserve('B2', 'task', limits(50, 2))
        self.assertEqual(20, second['limits']['max_total_tokens'])
        self.ledger.settle(first['ticket'], phase('b1', 50))
        self.ledger.settle(second['ticket'], phase('b2', 20))
        with self.assertRaisesRegex(ValueError, 'arm_cumulative'):
            self.ledger.reserve('B2', 'next', limits(1, 1))

    def test_unknown_freezes_dispatch_but_peer_usage_still_settles(self):
        a = self.ledger.reserve('B1', 'task', limits(40, 2))
        b = self.ledger.reserve('C1', 'task', limits(40, 2))
        self.ledger.settle(a['ticket'], phase('partial', 9, complete=False))
        with self.assertRaisesRegex(ValueError, 'unknown'):
            self.ledger.reserve('B2', 'task', limits(10, 1))
        self.ledger.settle(b['ticket'], phase('peer', 13))
        self.assertEqual(22, self.ledger.snapshot()['budget']['study']['tokens'])
        self.assertTrue(self.ledger.snapshot()['budget']['study']['uncertain'])

    def test_malformed_receipts_keep_valid_spend_and_do_not_drop_peer(self):
        a = self.ledger.reserve('B1', 'task', limits(40, 2))
        b = self.ledger.reserve('C1', 'task', limits(40, 2))
        invalid = phase('valid-subset', 7)
        invalid['receipts']['response_receipts'].append(dict(response_id='bad', usage=dict(total_tokens=-1)))
        with self.assertRaisesRegex(ValueError, 'usage_invalid'):
            self.ledger.settle(a['ticket'], invalid)
        self.ledger.settle(b['ticket'], phase('peer', 13))
        state = inspect_ledger(self.path)
        self.assertEqual(20, state['state']['budget']['study']['tokens'])
        self.assertTrue(state['state']['budget']['study']['uncertain'])
        self.assertIn('settlement_rejected', [e['kind'] for e in state['events']])

    def test_failed_run_is_not_success_and_next_planned_repetition_is_allowed(self):
        a = self.ledger.reserve('B1', 'task', limits(40, 2))
        self.ledger.settle(a['ticket'], phase('failed', 4, failure='task_timeout'))
        with self.assertRaisesRegex(ValueError, 'cannot_succeed'):
            self.ledger.finish('B1', dict(success=True))
        self.ledger.finish('B1', dict(success=False, reason='task_timeout'))
        second = self.ledger.reserve('B2', 'task', limits(10, 1))
        self.assertEqual('B2', second['run_id'])

    def test_idle_is_excluded_and_parallel_time_is_union(self):
        a = self.ledger.reserve('B1', 'first', limits(10, 1))
        self.clock.value = 10
        self.ledger.settle(a['ticket'], phase('first', 3))
        self.clock.value = 10010
        a = self.ledger.reserve('B1', 'second', limits(10, 1))
        b = self.ledger.reserve('C1', 'first', limits(10, 1))
        self.assertEqual(90, a['limits']['max_seconds'])
        self.clock.value += 7
        self.ledger.settle(a['ticket'], phase('second', 3))
        self.ledger.settle(b['ticket'], phase('peer', 3))
        self.assertEqual(17, self.ledger.snapshot()['active_seconds'])
        self.assertEqual(17, self.ledger.snapshot()['budget']['arms']['B1']['seconds'])

    def test_restart_cannot_reset_budget_or_retry_inflight_work(self):
        self.ledger.reserve('B1', 'task', limits(20, 1))
        self.ledger.close()
        with self.assertRaises(FileExistsError):
            DispatchBudget(self.path, self.runs, limits())
        state = inspect_ledger(self.path)['state']
        self.assertTrue(state['budget']['study']['uncertain'])
        self.assertEqual('interrupted', state['runs']['B1']['status'])
        self.assertEqual('planned', state['runs']['C1']['status'])
        self.assertEqual(1, len(state['tickets']))

    def test_host_preparation_cannot_reset_phase_deadline(self):
        a = self.ledger.reserve('B1', 'compression-plus-task', limits(20, 2, 100))
        self.clock.value = 25
        self.assertEqual(75, self.ledger.remaining(a['ticket'])['max_seconds'])
        self.clock.value = 101
        with self.assertRaisesRegex(ValueError, 'time_exhausted'):
            self.ledger.remaining(a['ticket'])
        result = self.ledger.settle(a['ticket'], phase('late', 7))
        self.assertTrue(result['observed_time_overrun'])
        self.assertEqual(7, self.ledger.snapshot()['budget']['study']['tokens'])
        with self.assertRaisesRegex(ValueError, 'cannot_succeed'):
            self.ledger.finish('B1', dict(success=True))

    def test_failed_journal_commit_returns_no_dispatch_grant(self):
        self.ledger.db.execute("CREATE TRIGGER reject_events BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected disk failure'); END")
        with self.assertRaises(Exception):
            self.ledger.reserve('B1', 'task', limits(20, 1))
        self.assertTrue(self.ledger.poisoned)
        self.assertEqual([], [e for e in inspect_ledger(self.path)['events'] if e['kind'] == 'reserved'])
        self.ledger.db.execute('DROP TRIGGER reject_events')
        with self.assertRaisesRegex(ValueError, 'not_live'):
            self.ledger.reserve('C1', 'task', limits(20, 1))

    def test_generated_input_is_bound_durably_once_before_call(self):
        grant=self.ledger.reserve('B1','selection',limits(20,1))
        self.ledger.bind_input(grant['ticket'],dict(request_sha256='actual-request',operation='selection'))
        audit=inspect_ledger(self.path)
        self.assertEqual('actual-request',audit['state']['tickets'][grant['ticket']]['input_binding']['request_sha256'])
        with self.assertRaisesRegex(ValueError,'already_bound'):
            self.ledger.bind_input(grant['ticket'],dict(request_sha256='changed'))


if __name__ == '__main__':
    unittest.main()
