"""Matrix coverage must hold within each task, not just in a pooled count."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
from native_task_matrix import paired_plan, settle_matrix, run_matrix
from native_repeated_pairs import schedule
from test_native_repeated_pairs import plan_at, outcome


class TaskMatrixTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        tasks=[]
        for i in range(5):
            plan=plan_at(self.root/f'task{i}')
            pairs=deepcopy(plan['pairs'][:3])
            conditions=pairs[0]['conditions']
            conditions['task_contract_sha256']=str(i+1)*64
            for pair in pairs:
                del pair['conditions']
                for arm in pair['arms'].values():
                    arm['ports']=[p+i*100 for p in arm['ports']]
            tasks.append(dict(id=f'task{i}',conditions=conditions,pairs=pairs))
        self.matrix=dict(kind='native_wsc_task_matrix_v1',parallel_pairs=2,tasks=tasks)

    def observations(self):
        return {j['pair_id']+'/'+j['arm']: outcome(j) for j in schedule(paired_plan(self.matrix))}

    def test_five_tasks_three_pairs_interleave_into_thirty_isolated_trajectories(self):
        plan=paired_plan(self.matrix)
        self.assertEqual([f'task{i}/p0' for i in range(5)], [p['id'] for p in plan['pairs'][:5]])
        jobs=schedule(plan)
        self.assertEqual(30,len(jobs))
        self.assertEqual(4,sum(j['wave']==0 for j in jobs))
        self.assertEqual(2,sum(j['wave']==7 for j in jobs))
        self.assertEqual(30,len({j['resources']['workspace'] for j in jobs}))

    def test_two_repeats_or_four_tasks_cannot_start(self):
        for mode in ('task','repeat'):
            matrix=deepcopy(self.matrix)
            (matrix['tasks'] if mode=='task' else matrix['tasks'][0]['pairs']).pop()
            with self.assertRaises(ValueError):
                run_matrix(matrix,lambda *a:self.fail('started'),self.root/mode)
            self.assertFalse((self.root/mode).exists())

    def test_each_task_gets_own_three_pair_statistics(self):
        result=settle_matrix(self.matrix,self.observations())
        self.assertTrue(result['all_tasks_have_three_valid_pairs'])
        self.assertEqual(15,result['total_valid_task_pairs'])
        for task in result['tasks']:
            self.assertEqual(3,task['matched_success_resource_differences']['total_tokens']['pairs'])
            self.assertEqual(-5,task['matched_success_resource_differences']['total_tokens']['median'])
        self.assertEqual('not_established',result['statistical_significance'])
        self.assertNotIn('minimum_five_met',result)

    def test_many_valid_pairs_elsewhere_cannot_replace_missing_repeat(self):
        observations=self.observations()
        del observations['task0/p2/C']
        result=settle_matrix(self.matrix,observations)
        self.assertEqual(14,result['total_valid_task_pairs'])
        self.assertFalse(result['all_tasks_have_three_valid_pairs'])
        self.assertFalse(result['tasks'][0]['three_repetitions_met'])
        self.assertTrue(all(t['three_repetitions_met'] for t in result['tasks'][1:]))
        self.assertIsNone(result['tasks'][0]['cost_by_arm']['C']['tokens_per_success'])

    def test_quality_failure_is_a_repeat_and_its_cost_is_retained(self):
        observations=self.observations()
        result=observations['task0/p1/C']['result']
        result['state']='task_failed'
        result['quality']['status']='failed'
        settled=settle_matrix(self.matrix,observations)
        self.assertTrue(settled['all_tasks_have_three_valid_pairs'])
        self.assertEqual(1,settled['tasks'][0]['quality_counts']['B_only_passed'])
        self.assertEqual(345/2,settled['tasks'][0]['cost_by_arm']['C']['tokens_per_success']['total_tokens'])

    def test_resource_collision_across_tasks_is_rejected(self):
        self.matrix['tasks'][1]['pairs'][0]['arms']['C']['workspace']=self.matrix['tasks'][0]['pairs'][0]['arms']['B']['workspace']
        with self.assertRaisesRegex(ValueError,'resource_overlap'):
            paired_plan(self.matrix)

    def test_matrix_runs_thirty_callbacks_once_and_saves_original_registration(self):
        import json
        seen=[]
        def worker(job, record_phase):
            seen.append(job['pair_id']+'/'+job['arm'])
            result=outcome(job)['result']
            record_phase(result['phases'][0])
            return result
        result=run_matrix(self.matrix,worker,self.root/'run')
        self.assertTrue(result['all_tasks_have_three_valid_pairs'])
        self.assertEqual(30,len(seen))
        self.assertEqual(30,len(set(seen)))
        saved=json.loads((self.root/'run'/'registration.json').read_text(encoding='utf-8'))
        self.assertEqual(self.matrix,saved['matrix_registration'])
        self.assertTrue((self.root/'run'/'matrix-result.json').is_file())


if __name__=='__main__':
    unittest.main()
