import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.followup_allocation import followup
from acceptance_matrix_v1.workspace_runtime import digest


class FollowupChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'coordinator-private').mkdir()
        (self.root/'coordinator-private/ledger.db').write_bytes(b'closed-fixture')
        limits=dict(max_total_tokens=2000000,max_responses=64,max_seconds=2400)
        closure=dict(budget=dict(status='closed',active_seconds=195.047,
            budget=dict(study=dict(limits=limits,tokens=262500,responses=6))))
        (self.root/'closure.json').write_text(json.dumps(closure),encoding='utf-8')
        self.receipt=dict(status='per_run_usage_reconciled',local_batch_usage_complete=True,
            closure_sha256=digest(self.root/'closure.json'),ledger_sha256=digest(self.root/'coordinator-private/ledger.db'),
            known_tokens=262500,known_responses=6,
            arithmetic_remainder=dict(max_total_tokens=1737500,max_responses=58,max_seconds=2204))
        self.write()
    def write(self):(self.root/'per-run-reconciliation.json').write_text(json.dumps(self.receipt),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def test_residual_only_and_equal_BC(self):
        value=followup(self.root)
        self.assertEqual(1737500,value['limits']['max_total_tokens'])
        self.assertEqual(value['run_limits']['Bprime'],value['run_limits']['C'])
    def test_changed_remainder_rejected(self):
        self.receipt['arithmetic_remainder']['max_total_tokens']+=1;self.write()
        with self.assertRaisesRegex(ValueError,'remainder_changed'):followup(self.root)
    def test_duplicate_claim_rejected(self):
        (self.root/'next-runtime-group.claim.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'already_claimed'):followup(self.root)


if __name__=='__main__':unittest.main()
