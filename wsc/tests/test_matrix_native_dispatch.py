from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.dispatch_budget import DispatchBudget, inspect_ledger
from acceptance_matrix_v1.native_dispatch import execute_bound_stage


class NativeDispatchChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.seconds = 0
        self.limits = dict(max_total_tokens=100, max_responses=10, max_seconds=100)
        self.binding = dict(workspace=str(self.work), model='model', effort='max', history_sha256='history-seal',
                            request_sha256=sha256(b'request').hexdigest())
        self.ledger = DispatchBudget(self.work/'ledger.db', {'run': dict(arm='Bprime', limits=self.limits,
                     binding=self.binding)}, self.limits, clock=lambda: self.seconds)
    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def opener(self):
        self.assertEqual(1, len(inspect_ledger(self.work/'ledger.db')['state']['tickets']))
        self.seconds += 5
        owner = SimpleNamespace(close=lambda: None)
        session = SimpleNamespace(registration=self.binding, matrix_import_proof=dict(imported_items_sha256='history-seal'),
                                  server=SimpleNamespace(owner=owner))
        def execute(request, destination, limits, callback, **kwargs):
            self.assertEqual(95, limits['max_seconds'])
            result = dict(usage_complete=True, failure=None, receipts=dict(response_receipts=[
                dict(response_id='actual-response', usage=dict(total_tokens=7))]))
            callback(result)
            return result
        def close():
            self.seconds += 3
        session.execute_stage, session.close = execute, close
        return session

    def test_persisted_grant_precedes_open_and_cleanup_time_is_charged(self):
        result = execute_bound_stage(self.ledger, 'run', 'task', self.limits, self.opener, 'request', self.work/'phase')
        self.assertEqual(7, result['settlement']['known_total_tokens'])
        self.assertEqual(8, self.ledger.snapshot()['active_seconds'])
        self.assertFalse(self.ledger.snapshot()['budget']['study']['uncertain'])

    def test_changed_request_never_opens_or_reserves(self):
        with self.assertRaisesRegex(ValueError, 'request_binding'):
            execute_bound_stage(self.ledger, 'run', 'task', self.limits, self.opener, 'changed', self.work/'phase')
        self.assertEqual({}, self.ledger.snapshot()['tickets'])

    def test_failed_open_is_unknown_and_never_retried(self):
        attempts = []
        def fail():
            attempts.append(1)
            raise RuntimeError('open_failed')
        with self.assertRaisesRegex(RuntimeError, 'open_failed'):
            execute_bound_stage(self.ledger, 'run', 'task', self.limits, fail, 'request', self.work/'phase')
        self.assertEqual([1], attempts)
        self.assertTrue(self.ledger.snapshot()['budget']['study']['uncertain'])

    def test_wrong_import_seal_is_closed_without_model_execution(self):
        closed = []
        def wrong():
            session = self.opener()
            session.matrix_import_proof = dict(imported_items_sha256='wrong')
            session.execute_stage = lambda *a, **kw: self.fail('unbound model execution')
            session.close = lambda: closed.append(True)
            return session
        with self.assertRaisesRegex(ValueError, 'history_binding_changed'):
            execute_bound_stage(self.ledger, 'run', 'task', self.limits, wrong, 'request', self.work/'phase')
        self.assertEqual([True], closed)

    def test_duplicate_callback_retains_known_spend_once_and_freezes(self):
        def duplicate():
            session = self.opener()
            original = session.execute_stage
            def execute(request, destination, limits, callback, **kwargs):
                result = original(request, destination, limits, callback, **kwargs)
                callback(result)
                return result
            session.execute_stage = execute
            return session
        with self.assertRaisesRegex(ValueError, 'response_reused'):
            execute_bound_stage(self.ledger, 'run', 'task', self.limits, duplicate, 'request', self.work/'phase')
        self.assertEqual(7, self.ledger.snapshot()['budget']['study']['tokens'])
        self.assertTrue(self.ledger.snapshot()['budget']['study']['uncertain'])


if __name__ == '__main__':
    unittest.main()
