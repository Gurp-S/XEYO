from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
from types import SimpleNamespace
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'benchmarks')]
from acceptance_matrix_v1 import task_cell
from acceptance_matrix_v1.paired_cell import Cell
from acceptance_matrix_v1.permissions import runtime_startup_flags


class TaskRouteChecks(TestCase):
    def test_v2_evaluator_requires_explicit_policy_and_routes_to_new_checker(self):
        with TemporaryDirectory() as d:
            out=Path(d);(out/'coordinator-private').mkdir();(out/'A').mkdir()
            (out/'A/migrate.py').write_text('# fixture',encoding='utf-8')
            plan={'task_id':'T3','task_evaluator_policy':'implementation_neutral_t3_v2'}
            with patch.object(task_cell,'load_candidate',return_value='candidate'), \
                 patch('acceptance_matrix_v1.acceptor_t3_v2.accept_t3_v2',return_value={'success':True,'policy':'v2'}) as check:
                cell=task_cell.TaskCell('A',plan,out,object(),{'task':'T3'},task_id='T3')
                self.assertEqual('v2',cell.evaluate_artifact()['policy']);check.assert_called_once_with('candidate')
    def test_unknown_evaluator_policy_rejected_before_folder_creation(self):
        with TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'evaluator_policy_unregistered'):
                task_cell.TaskCell('A',{'task_id':'T3','task_evaluator_policy':'unknown'},d,object(),{'task':'T3'},task_id='T3')
            self.assertEqual([],list(Path(d).iterdir()))
    def test_runtime_override_is_opt_in_and_cannot_change_other_host_controls(self):
        self.assertEqual([],runtime_startup_flags({}))
        self.assertEqual(['mcp_servers.node_repl.enabled=false'],runtime_startup_flags({'runtime_startup_flags':['mcp_servers.node_repl.enabled=false']}))
        with self.assertRaisesRegex(ValueError,'matrix_runtime_startup_flags_unregistered'):
            runtime_startup_flags({'runtime_startup_flags':['sandbox_mode="danger-full-access"']})
    def test_mismatched_or_unknown_task_rejected_before_ledger_or_folder(self):
        for task,plan,inputs in [('T3',{'task_id':'T1'},{'task':'T3'}),
                                 ('T3',{'task_id':'T3'},{'task':'T1'}),
                                 ('unknown',{'task_id':'unknown'},{'task':'unknown'})]:
            with TemporaryDirectory() as d:
                with self.assertRaisesRegex(ValueError,'matrix_task_binding_mismatch'):
                    task_cell.TaskCell('C',plan,d,object(),inputs,task_id=task)
                self.assertEqual([],list(Path(d).iterdir()))

    def test_both_t3_paths_use_migration_artifact_and_not_retry_artifact(self):
        for cls in (task_cell.TaskCell,task_cell.TaskBaselineCell):
            with TemporaryDirectory() as d:
                out=Path(d);(out/'coordinator-private').mkdir();(out/'A').mkdir()
                (out/'A/migrate.py').write_text('# candidate',encoding='utf-8')
                marker=object();seen=[]
                with patch.dict(task_cell.TASKS,{'T3':('migrate.py',lambda m:seen.append(m) or {'success':True})}), \
                     patch.object(task_cell,'load_candidate',return_value=marker) as load:
                    cell=cls('A',{'task_id':'T3'},out,object(),{'task':'T3'},task_id='T3')
                    self.assertTrue(cell.evaluate_artifact()['success'])
                    load.assert_called_once_with(out/'A/migrate.py')
                    self.assertEqual([marker],seen)

    def test_default_t1_path_still_uses_original_evaluator(self):
        with TemporaryDirectory() as d:
            out=Path(d);(out/'coordinator-private').mkdir()
            cell=Cell('C',{},out,object(),{})
            with patch('acceptance_matrix_v1.paired_cell.load_candidate',return_value='t1') as load, \
                 patch('acceptance_matrix_v1.paired_cell.accept_t1',return_value={'success':True}) as accept:
                self.assertTrue(cell.evaluate_artifact()['success'])
                load.assert_called_once_with(out/'C/retry_client.py');accept.assert_called_once_with('t1')

    def test_namespaced_baseline_finishes_its_own_ledger_record(self):
        with TemporaryDirectory() as d:
            out=Path(d);(out/'coordinator-private').mkdir()
            completed=[]
            ledger=SimpleNamespace(finish=lambda identity,result:completed.append(identity))
            cell=task_cell.TaskBaselineCell('A',{'task_id':'T3'},out,ledger,{'task':'T3'},task_id='T3',ledger_id='T3:A')
            cell.start=lambda label:(_ for _ in ()).throw(ValueError('fixture fails before model call'))
            cell.run()
            self.assertEqual(['T3:A'],completed)


if __name__=='__main__':main()
