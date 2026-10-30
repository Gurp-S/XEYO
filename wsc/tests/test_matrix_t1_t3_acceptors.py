from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]/'benchmarks'
sys.path.insert(0, str(BASE))
from acceptance_matrix_v1.acceptors import accept_t1, accept_t3, load_candidate

SUITE = BASE/'acceptance_matrix_v1'


class TaskAcceptorChecks(unittest.TestCase):
    def setUp(self):
        self.retry = load_candidate(SUITE/'calibration/retry_reference.py')
        self.migration = load_candidate(SUITE/'calibration/migration_reference.py')

    def failed(self, result, check_id):
        return not next(r for r in result['checks'] if r['check_id'] == check_id)['passed']

    def test_retry_reference_passes_all_eleven_cases(self):
        result = accept_t1(self.retry)
        self.assertTrue(result['success'], result)
        self.assertEqual(11, len(result['checks']))
        self.assertEqual([], result['constraint_violations'])

    def test_migration_reference_passes_all_ten_cases(self):
        result = accept_t3(self.migration)
        self.assertTrue(result['success'], result)
        self.assertEqual(10, len(result['checks']))
        self.assertEqual([], result['constraint_violations'])

    def test_starters_fail_but_every_check_still_runs(self):
        for relative, acceptor, count in [('t1_retry/starter/retry_client.py', accept_t1, 11),
                                          ('t3_migration/starter/migrate.py', accept_t3, 10)]:
            result = acceptor(load_candidate(SUITE/'tasks'/relative))
            self.assertFalse(result['success'])
            self.assertEqual(count, len(result['checks']))

    def test_retry_status_error_is_detected(self):
        def incorrect(jobs, send, max_attempts=3):
            def changed(job, attempt):
                response = send(job, attempt)
                return {**response, 'status': 500} if response['status'] == 429 else response
            return self.retry.run_batch(jobs, changed, max_attempts)
        self.assertTrue(self.failed(accept_t1(SimpleNamespace(run_batch=incorrect)), 'retry-statuses'))

    def test_global_identity_instead_of_tenant_identity_is_detected(self):
        def incorrect(jobs, send, max_attempts=3):
            return self.retry.run_batch([{**job, 'tenant': 'a'} for job in jobs], send, max_attempts)
        self.assertTrue(self.failed(accept_t1(SimpleNamespace(run_batch=incorrect)), 'scoped-identity'))

    def test_deleting_archived_rows_is_detected(self):
        def incorrect(db):
            self.migration.migrate(db)
            db.execute('DELETE FROM projects WHERE archived=1')
        self.assertTrue(self.failed(accept_t3(SimpleNamespace(migrate=incorrect)), 'preserve-rows'))

    def test_committing_caller_transaction_is_detected(self):
        def incorrect(db):
            self.migration.migrate(db)
            db.commit()
        self.assertTrue(self.failed(accept_t3(SimpleNamespace(migrate=incorrect)), 'caller-transaction'))

    def test_replay_reset_of_row_versions_is_detected(self):
        def incorrect(db):
            self.migration.migrate(db)
            db.execute('UPDATE projects SET row_version=1')
        self.assertTrue(self.failed(accept_t3(SimpleNamespace(migrate=incorrect)), 'replay'))

    def test_ignoring_declared_version_is_detected(self):
        def incorrect(db):
            db.execute('UPDATE schema_version SET version=1')
            self.migration.migrate(db)
        self.assertTrue(self.failed(accept_t3(SimpleNamespace(migrate=incorrect)), 'unsupported-version'))


if __name__ == '__main__':
    unittest.main()
