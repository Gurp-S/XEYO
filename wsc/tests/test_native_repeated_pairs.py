"""Offline scheduling and cost-retention checks; no native/model processes."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import FIELDS, digest
from native_repeated_pairs import schedule, run_workers, settle


def plan_at(root):
    pairs = []
    for index in range(5):
        arms = {}
        for offset, arm in enumerate(('B', 'C')):
            prefix = root / f'{index}-{arm}'
            arms[arm] = dict(strategy='native_control' if arm == 'B' else 'registered_wsc',
                             workspace=str(prefix / 'workspace'), output=str(prefix / 'output'),
                             browser_profile=str(prefix / 'browser'), ports=[18000 + 2 * index + offset])
        pairs.append(dict(id=f'p{index}', arms=arms, conditions=dict(
            source_manifest_sha256='a'*64, task_contract_sha256='b'*64, tools_sha256='c'*64,
            model='offline-fixture', effort='max', budget={'responses': 2})))
    return dict(kind='native_wsc_repeated_pairs_v1', parallel_pairs=2, pairs=pairs)


def phase(job):
    c = job['arm'] == 'C'
    usage = dict(zip(FIELDS, (100, 50, 0, 15 if c else 20, 5, 115 if c else 120)))
    return dict(seconds=2 if c else 3, usage_complete=True, receipts={'response_receipts': [
        dict(response_id=job['pair_id'] + '/' + job['arm'], usage=usage)]})


def outcome(job):
    return dict(job=deepcopy(job), worker_error=None, result=dict(
        state='completed', conditions_sha256=job['conditions_sha256'], admission_matched=True,
        quality=dict(status='passed', evidence_sha256='d'*64), phases=[phase(job)]))


class RepeatedPairsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan = plan_at(self.root)

    def observations(self):
        return {j['pair_id']+'/'+j['arm']: outcome(j) for j in schedule(self.plan)}

    def test_five_pairs_is_required_before_any_worker(self):
        self.plan['pairs'].pop()
        seen = []
        with self.assertRaisesRegex(ValueError, 'minimum_five'):
            run_workers(self.plan, lambda *args: seen.append(args), self.root/'run')
        self.assertEqual([], seen)
        self.assertFalse((self.root/'run').exists())

    def test_resource_and_port_overlap_rejected_before_any_worker(self):
        for mode in ('nested', 'same', 'port', 'missing_arm'):
            with self.subTest(mode=mode):
                plan = deepcopy(self.plan)
                b = plan['pairs'][0]['arms']['B']
                c = plan['pairs'][1]['arms']['C']
                if mode == 'nested':
                    c['output'] = str(Path(b['workspace'])/'nested')
                elif mode == 'same':
                    c['browser_profile'] = b['workspace']
                elif mode == 'port':
                    c['ports'] = b['ports'][:]
                else:
                    del plan['pairs'][1]['arms']['C']
                with self.assertRaises(ValueError):
                    run_workers(plan, lambda *args: self.fail('worker started'), self.root/mode)

    def test_four_workers_overlap_waves_remain_ordered_and_inputs_are_isolated(self):
        jobs = schedule(self.plan)
        self.assertEqual(['B', 'C', 'C', 'B'], [j['arm'] for j in jobs[:4]])
        original = digest(self.plan)
        barriers = {0: threading.Barrier(4), 1: threading.Barrier(4), 2: threading.Barrier(2)}
        lock, completed = threading.Lock(), []

        def worker(job, record_phase):
            with lock:
                if job['wave']:
                    self.assertEqual(4*job['wave'], sum(w < job['wave'] for w in completed))
            barriers[job['wave']].wait(timeout=5)
            result = outcome(job)['result']
            record_phase(result['phases'][0])
            job['conditions']['budget']['responses'] = 999
            with lock:
                completed.append(job['wave'])
            return result

        result = run_workers(self.plan, worker, self.root/'run')
        self.assertEqual(10, len(completed))
        self.assertEqual(original, digest(self.plan))
        self.assertTrue(all(o['worker_error'] is None for o in result['worker_observations'].values()))
        self.assertTrue(settle(self.plan, result['worker_observations'])['minimum_five_met'])
        with self.assertRaises(FileExistsError):
            run_workers(self.plan, lambda *args: self.fail('replayed'), self.root/'run')

    def test_journal_survives_failure_and_keeps_paid_usage_unknown_total(self):
        seen = []
        def worker(job, record_phase):
            seen.append(job['pair_id']+'/'+job['arm'])
            current = phase(job)
            record_phase(current)
            if job['pair_id'] == 'p0' and job['arm'] == 'C':
                current['receipts']['response_receipts'][0]['usage']['total_tokens'] = 9999
                raise RuntimeError('after paid phase')
            return outcome(job)['result']
        raw = run_workers(self.plan, worker, self.root/'run')
        result = settle(self.plan, raw['worker_observations'])
        self.assertEqual(10, len(seen))
        self.assertEqual(10, len(set(seen)))
        self.assertEqual(0, raw['automatic_retries'])
        self.assertEqual(4, result['valid_task_pairs'])
        failed = result['arms']['p0/C']['usage']
        self.assertEqual(115, failed['known_usage']['total_tokens'])
        self.assertFalse(failed['complete'])
        self.assertIsNone(failed['complete_usage'])
        self.assertEqual(575, result['cost_by_arm']['C']['known_usage']['total_tokens'])
        self.assertIsNone(result['cost_by_arm']['C']['complete_usage'])
        self.assertEqual(10, len(list((self.root/'run'/'phases').rglob('*.json'))))

    def test_failure_costs_count_toward_cost_per_success(self):
        observations = self.observations()
        failed = observations['p0/C']['result']
        failed['state'] = 'budget_exhausted'
        failed['quality']['status'] = 'failed'
        result = settle(self.plan, observations)
        self.assertTrue(result['minimum_five_met'])
        self.assertEqual(1, result['quality_counts']['B_only_passed'])
        self.assertEqual(4, result['matched_success_resource_differences']['total_tokens']['pairs'])
        self.assertEqual(-5, result['matched_success_resource_differences']['total_tokens']['median'])
        self.assertEqual(575/4, result['cost_by_arm']['C']['tokens_per_success']['total_tokens'])
        self.assertEqual(120, result['cost_by_arm']['B']['tokens_per_success']['total_tokens'])
        self.assertIsNone(result['cash'])
        self.assertEqual('not_established', result['statistical_significance'])

    def test_missing_or_unqualified_observation_cannot_supply_fifth_pair(self):
        for mode in ('missing', 'binding', 'no_phases', 'evidence', 'worker_error'):
            with self.subTest(mode=mode):
                observations = self.observations()
                out = observations['p0/C']
                if mode == 'missing':
                    del observations['p0/C']
                elif mode == 'binding':
                    out['result']['conditions_sha256'] = 'e'*64
                elif mode == 'no_phases':
                    out['result']['phases'] = []
                elif mode == 'evidence':
                    out['result']['quality']['evidence_sha256'] = 'not-a-digest'
                else:
                    out['worker_error'] = 'after result'
                result = settle(self.plan, observations)
                self.assertFalse(result['minimum_five_met'])
                self.assertEqual(4, result['valid_task_pairs'])
                self.assertIsNone(result['cost_by_arm']['C']['tokens_per_success'])

    def test_receipts_cannot_be_shared_between_arms(self):
        observations = self.observations()
        observations['p0/C']['result']['phases'][0]['receipts'] = deepcopy(
            observations['p0/B']['result']['phases'][0]['receipts'])
        with self.assertRaisesRegex(ValueError, 'shared_between_arms'):
            settle(self.plan, observations)

    def test_invalid_time_cannot_become_performance_result(self):
        for seconds in (-1, float('nan'), float('inf'), True):
            with self.subTest(seconds=seconds):
                observations = self.observations()
                observations['p0/C']['result']['phases'][0]['seconds'] = seconds
                with self.assertRaisesRegex(ValueError, 'phase_seconds_invalid'):
                    settle(self.plan, observations)

    def test_scheduler_evidence_directory_cannot_overlap_worker(self):
        target = Path(self.plan['pairs'][0]['arms']['B']['workspace'])/'audit'
        with self.assertRaisesRegex(ValueError, 'destination_overlap'):
            run_workers(self.plan, lambda *args: self.fail('worker started'), target)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
