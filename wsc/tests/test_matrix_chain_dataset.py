"""Calibrate deterministic chain checks, never compress or invoke a model."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import TestCase,main

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.chain_dataset import build_chain,release_round
from acceptance_matrix_v1.chain_evaluation import evaluate_claims,evaluate_code,evaluate_work_state
from acceptance_matrix_v1.calibration import migration_reference


def reference(task,policy):
    if task=='T1':
        # Coordinator-only positive control; never a tested compression algorithm.
        source=(ROOT/'benchmarks/acceptance_matrix_v1/calibration/retry_reference.py').read_text(encoding='utf-8')
        namespace={}
        exec(compile(source.replace('not in (429, 503)','not in '+repr(tuple(policy['retry_statuses']))),
                     '<private-chain-calibration>','exec'),namespace)
        return SimpleNamespace(run_batch=namespace['run_batch'])
    def migrate(db):
        if any(len(row[0])>policy['max_title_codepoints'] for row in db.execute('SELECT title FROM projects')):
            raise ValueError('title_limit')
        return migration_reference.migrate(db)
    return SimpleNamespace(migrate=migrate)


def claims(oracle):
    return [dict(assertion_id=key,value=deepcopy(value),**deepcopy(oracle['expected_bindings'][key]))
            for key,value in oracle['expected_assertions'].items()]


class ChainDatasetChecks(TestCase):
    def test_reproducible_six_updates_and_scheduled_release_has_no_future_round(self):
        for task in ('T1','T3'):
            schedule,private=build_chain(task,seed=17)
            self.assertEqual((schedule,private),build_chain(task,seed=17))
            self.assertEqual([2,4,6],schedule['checkpoints'])
            self.assertEqual(6,len(schedule['rounds']))
            self.assertFalse(schedule['history_dependency_qualified'])
            self.assertNotIn('expected_assertions',schedule)
            first=release_round(schedule,1)
            for row in first:
                if row['type']=='function_call_output':
                    record=json.loads(row['output'])
                    self.assertNotEqual(task+'/policy/r4',record['source_id'])
            first.clear();self.assertTrue(schedule['rounds'][0]['history_items'])

    def test_positive_and_previous_code_controls_at_all_checkpoints(self):
        for task in ('T1','T3'):
            _,private=build_chain(task,noise_per_round=0)
            for number in (2,4,6):
                with self.subTest(task=task,round=number):
                    oracle=private['rounds'][str(number)]
                    current=evaluate_code(reference(task,oracle['policy']),oracle)
                    self.assertTrue(current['success'],current)
                    previous=private['rounds'][str(number-1)]['policy']
                    stale=evaluate_code(reference(task,previous),oracle)
                    self.assertFalse(stale['success'],stale)

    def test_correct_and_inverted_current_historical_claims(self):
        for task in ('T1','T3'):
            _,private=build_chain(task);oracle=private['rounds']['4']
            correct=claims(oracle);self.assertTrue(evaluate_claims(correct,oracle)['success'])
            old=deepcopy(correct)
            for item in old:
                if item['assertion_id']=='current_policy':
                    item.update(value=oracle['expected_assertions']['round1_policy'],
                                **oracle['expected_bindings']['round1_policy'])
            self.assertFalse(evaluate_claims(old,oracle)['success'])

    def test_identical_value_in_wrong_epoch_does_not_prove_current_applicability(self):
        _,private=build_chain('T1');oracle=private['rounds']['6'];items=claims(oracle)
        for item in items:
            if item['assertion_id']=='current_state':item['source_id']='T1/work-item/4'
        result=evaluate_claims(items,oracle)
        self.assertEqual(5,result['exact_fields']['exact_answer_correct'])
        self.assertEqual(5,result['exact_fields']['citation_byte_matches'])
        self.assertFalse(result['success'])

    def test_state_artifact_is_exact_and_rejects_old_revision_duplicate_keys_and_wrong_relation(self):
        _,private=build_chain('T3');oracle=private['rounds']['4']
        expected=oracle['expected_work_state']
        self.assertTrue(evaluate_work_state(json.dumps(expected),oracle)['success'])
        for state in [dict(expected,revision=3),dict(expected,basis_policy='T3/policy/r3')]:
            self.assertFalse(evaluate_work_state(json.dumps(state),oracle)['success'])
        self.assertFalse(evaluate_work_state('{"revision":3,"revision":4}',oracle)['success'])

    def test_release_rejects_boolean_or_out_of_range_rounds(self):
        schedule,_=build_chain('T1')
        for number in (True,0,7):
            with self.assertRaises(ValueError):release_round(schedule,number)

    def test_sealed_initial_history_reused_without_rewriting_events(self):
        original,_=build_chain('T1')
        reused,_=build_chain('T1',initial_history=original['initial_history'])
        self.assertTrue(reused['initial_history_reused'])
        self.assertEqual(original['initial_history'],reused['initial_history'])
        self.assertEqual(original['initial_history_sha256'],reused['initial_history_sha256'])
        with self.assertRaisesRegex(ValueError,'identity_invalid'):
            build_chain('T3',initial_history=original['initial_history'])


if __name__=='__main__':main()
