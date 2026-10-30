from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'benchmarks')]
from acceptance_matrix_v1.paired_cell import Cell


class CellIdentityChecks(unittest.TestCase):
    def test_namespaced_ledger_retains_canonical_actor(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary);(out/'coordinator-private').mkdir()
            observed=[]
            ledger=SimpleNamespace(reserve=lambda *a:observed.append(a) or {'ticket':'ticket'})
            cell=Cell('C',{'run_limits':{'C':{'limit':1}}},out,ledger,{},ledger_id='r2:C')
            self.assertEqual('ticket',cell.start('selection'))
            self.assertEqual('r2:C',observed[0][0])
            self.assertEqual('C',cell.name)
            self.assertEqual(out/'C',cell.work)
    def test_existing_caller_identity_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary);(out/'coordinator-private').mkdir()
            cell=Cell('Bprime',{},out,object(),{})
            self.assertEqual('Bprime',cell.run_id)


if __name__=='__main__':unittest.main()
