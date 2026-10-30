from hashlib import sha256
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_native_task_recovery as baseline


class SystemTaskAdmissionChecks(unittest.TestCase):
    setUp = baseline.OrdinaryTaskRecoveryChecks.setUp

    def facts(self):
        return dict(comparison='system_blackbox',capacity_status='unobserved',request_input_tokens=None,
            thread_id=self.port.owner,workspace=self.port.workspace,request_sha256=sha256(b'query').hexdigest(),
            source_digest=self.reader.snapshot_binding['source_digest'],budget_ticket='ticket',
            limits=dict(max_total_tokens=100,max_responses=2,max_seconds=10))

    def execute(self, facts):
        return self.port.execute_stage('query',Path(self.port.workspace)/'phase',self.facts()['limits'],lambda p:None,
                                       system_admission=lambda *a:facts)

    def test_unknown_capacity_is_explicit_and_does_not_skip_owner_binding(self):
        self.execute(self.facts())
        self.assertEqual('unobserved',self.port.last_system_admission['capacity_status'])
        self.assertEqual(1,self.reader.calls)

    def test_changed_request_or_thread_is_rejected_without_source_io(self):
        for field in ('request_sha256','thread_id','source_digest'):
            facts=self.facts();facts[field]='changed'
            with self.assertRaisesRegex(ValueError,'binding_changed'):
                self.execute(facts)
        self.assertEqual(0,self.reader.calls)

    def test_constant_true_is_not_a_blackbox_admission(self):
        with self.assertRaisesRegex(ValueError,'admission_invalid'):
            self.execute(True)

    def test_budget_and_modes_are_not_implicit(self):
        facts=self.facts();facts['limits']['max_seconds']=0
        with self.assertRaisesRegex(ValueError,'budget_unbound'):
            self.execute(facts)
        with self.assertRaisesRegex(ValueError,'modes_conflict'):
            self.port.execute_stage('query',Path(self.port.workspace)/'phase',{},lambda p:None,
                system_admission=lambda *a:self.facts(),capacity_check=lambda *a:True)


if __name__=='__main__':
    unittest.main()
