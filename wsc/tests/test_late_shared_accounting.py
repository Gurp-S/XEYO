from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'experiments'),str(ROOT/'src')]
from late_recovery_qualification import LateCell
from native_application_budget import StudyBudget


class LateSharedAccountingTests(unittest.TestCase):
    def test_nonfirst_unknown_freezes_peer_admission(self):
        caps=dict(max_total_tokens=100,max_responses=3,max_seconds=100)
        before=StudyBudget({'R02/wsc':caps,'R03/wsc':caps},dict(max_total_tokens=200,max_responses=6,max_seconds=200))
        with self.assertRaisesRegex(ValueError,'application_budget_arm_missing'):before.mark_unknown('R01/wsc')
        self.assertFalse(before.snapshot()['study']['uncertain'])
        before.reserve('R02/wsc',caps)
        ledger=StudyBudget({'R02/wsc':caps,'R03/wsc':caps},dict(max_total_tokens=200,max_responses=6,max_seconds=200))
        cell=object.__new__(LateCell);cell.ledger=ledger;cell.repetition=3;cell.accounting_unknown()
        self.assertTrue(ledger.snapshot()['arms']['R03/wsc']['stopped'])
        self.assertFalse(ledger.snapshot()['arms']['R02/wsc']['stopped'])
        with self.assertRaisesRegex(ValueError,'application_budget_unknown_or_arm_missing'):ledger.reserve('R02/wsc',caps)


if __name__=='__main__':unittest.main()
