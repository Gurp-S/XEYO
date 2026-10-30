"""Admission and stop boundaries for the new staged task, without model calls."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import FIELDS, file_hash, read, save
from native_task_checks import grade
from native_task_checkpoint import generate_checkpoint
from native_runtime_probe import verify_runtime
import run_control_continuation as runner


def outcome(identity, complete=True):
    u = dict.fromkeys(FIELDS, 0)
    u.update(input_tokens=2, total_tokens=2)
    return {'completed': complete, 'failure': None if complete else 'registered_wall_cap',
            'usage_complete': complete, 'receipts': {'response_receipts': [
                {'response_id': identity, 'usage': u}]}}


class AcceptanceTests(unittest.TestCase):
    def test_checkpoint_preserves_source_scope_and_failed_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [
                {'type': 'session_meta', 'payload': {'id': 'fixture'}},
                {'type': 'turn_context', 'timestamp': 'original', 'payload': {'turn_id': 'turn', 'cwd': str(root)}},
                {'type': 'response_item', 'timestamp': 'original', 'payload': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': 'fixture task'}]}}]
            raw = root / 'source.jsonl'
            raw.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            phase = {'thread_id': 'fixture', 'rollout_sha256': file_hash(raw), 'completed': False,
                     'failure': 'registered_response_cap', 'usage_complete': False,
                     'usage_completion_evidence': {'turn_id': 'turn'}}
            acceptance = {'observed_at': 'checked', 'source_manifest_sha256': 'fixture-manifest',
                'names': ['first_scope'], 'tests': 1, 'passed': True, 'scope': 'fixture_only', 'grader_sha256': 'fixture'}
            seen = []
            def execute(request, schema):
                seen.append(request)
                return {'usage_complete': False, 'completed': False}, root / 'never-created.jsonl'
            with self.assertRaisesRegex(ValueError, 'checkpoint_generation_incomplete'):
                generate_checkpoint(root / 'checkpoint', root, raw, phase, acceptance,
                                    root / 'fixture-receipt.json', execute)
            self.assertEqual(1, len(seen))
            self.assertEqual({'source': 's4'}, seen[0]['execution_scope'])
            original = read(root / 'checkpoint/original-material.json')
            observed = json.loads(original['events'][1]['text'])
            self.assertEqual(['first_scope'], observed['names'])
            self.assertEqual('fixture_only', observed['scope'])
            interrupted = json.loads(original['events'][2]['text'])
            self.assertFalse(interrupted['host_phase_completed'])
            self.assertFalse(interrupted['usage_complete'])
            self.assertEqual('registered_response_cap', interrupted['host_stop_reason'])
            result = read(root / 'checkpoint/result.json')
            self.assertEqual('failed_preserved', result['status'])
            self.assertEqual(0, result['cursor'])
            self.assertFalse((root / 'checkpoint/package.json').exists())

    def test_actual_private_import_and_explicit_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(__file__).resolve().parents[1]
            result = grade(root, root / 'tests/test_control_retention.py', runner.METHODS[:1], Path(temp) / 'grade')
            self.assertTrue(result['passed'])
            self.assertEqual(1, result['tests'])
            self.assertEqual(runner.METHODS[:1], result['names'])
            self.assertTrue(Path(result['imported_from']).is_relative_to(Path(temp)))

    def test_duplicate_or_unknown_names_cannot_produce_passing_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(__file__).resolve().parents[1]
            with self.assertRaisesRegex(ValueError, 'names_invalid'):
                grade(root, root / 'tests/test_control_retention.py', runner.METHODS[:1] * 2, Path(temp) / 'bad')
            result = grade(root, root / 'tests/test_control_retention.py',
                           ['ControlRetentionTests.test_missing'], Path(temp) / 'unknown')
            self.assertFalse(result['passed'])
            self.assertEqual(1, len(result['errors']))


class DriverTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.area = Path(tmp.name)
        self.initial = {'AGENTS.md': 'rules'}
        save(self.area / 'registration.json', {'workspace': str(self.area / 'workspace'),
            'initial_manifest': self.initial, 'stages': runner.STAGES, 'grader': 'unused', 'executable': 'unused'})
        self.opened = [{'thread': {'id': name, 'path': 'unused'}} for name in ('source', 'generator', 'C')]

    def execute(self, outcomes, *, passed=True, runtime_ok=True, after=None, stages=None):
        receipt = {'source_manifest_sha256': 'current', 'names': ['named'], 'tests': 1,
                   'passed': passed, 'grader_sha256': 'grader'}
        archived = {str(i): {'receipts': {'response_receipts': o['receipts']['response_receipts']}}
                    for i, o in enumerate(outcomes)}
        def checkpoint(*args, **kwargs):
            generated, _ = args[-1]({}, {})
            runner.require_completed(generated)
            return {'items': []}
        with patch.object(runner, 'verify_pins'), patch.object(runner, 'manifest', return_value=self.initial), \
             patch.object(runner, 'NativeRPC') as rpc, patch.object(runner, 'initialize', return_value={}), \
             patch.object(runner, 'verify_runtime', return_value={},
                          side_effect=None if runtime_ok else ValueError('native_task_runtime_unavailable')), \
             patch.object(runner, 'open_thread', side_effect=self.opened), \
             patch.object(runner, 'import_items'), patch.object(runner, 'audit_host'), patch.object(runner, 'audit_import'), \
             patch.object(runner, 'observe', return_value={'response_count': 0}), \
             patch.object(runner, 'archive_workspace', return_value={'manifest': self.initial},
                          side_effect=None if after is None else [{'manifest': self.initial}, {'manifest': after}]), \
             patch.object(runner, 'archive_threads', return_value=archived), \
             patch.object(runner, 'generate_checkpoint', side_effect=checkpoint) as checkpoint_mock, \
             patch.object(runner, 'prepare_message_checkpoint', return_value={'items': []}), \
             patch.object(runner, 'grade', return_value=receipt) as checks, \
             patch.object(runner, 'phase', side_effect=outcomes) as calls:
            rpc.return_value.__enter__.return_value.call.return_value = {}
            runner.run(self.area, stages=stages)
        return read(self.area / 'result.json'), calls, checks, checkpoint_mock

    def test_unavailable_native_runtime_stops_before_any_model_phase(self):
        result, calls, checks, checkpoint = self.execute([], runtime_ok=False)
        self.assertEqual('stopped', result['status'])
        self.assertIn('native_task_runtime_unavailable', result['error'])
        self.assertEqual(0, result['usage']['response_count'])
        calls.assert_not_called()
        checks.assert_not_called()
        checkpoint.assert_not_called()

    def test_legitimate_existing_test_edit_reaches_independent_acceptance(self):
        self.initial['tests/existing.py'] = 'old'
        reg = read(self.area / 'registration.json')
        reg['initial_manifest'] = self.initial
        (self.area / 'registration.json').write_text(json.dumps(reg), encoding='utf-8')
        result, _, checks, _ = self.execute([outcome('a')], passed=False,
                                           after={**self.initial, 'tests/existing.py': 'new'})
        checks.assert_called_once()
        self.assertIn('control_acceptance_failed', result['error'])
        self.assertNotIn('protected_input', result['error'])

    def test_one_source_one_generation_two_C_turns_and_no_double_billing(self):
        result, calls, checks, _ = self.execute([outcome(n) for n in 'abcd'])
        self.assertEqual('C_task_executed_semantic_review_pending', result['status'])
        self.assertEqual(4, result['usage']['response_count'])
        self.assertEqual(8, result['usage']['complete_usage']['total_tokens'])
        self.assertEqual(2, checks.call_count)
        self.assertEqual(['fresh_single_turn'] * 3 + ['append_only_turn'],
                         [c.args[2]['accounting_scope'] for c in calls.call_args_list])
        self.assertIs(calls.call_args_list[2].args[1], calls.call_args_list[3].args[1])

    def test_recovery_skips_source_phase_and_preserves_unknown_historical_usage(self):
        for name, value in {'phase': {}, 'receipt': {'source_manifest_sha256': 'old', 'names': ['old'],
                'tests': 1, 'passed': False, 'grader_sha256': 'grader'},
                'old-result': {'usage': {'known_usage': {'total_tokens': 900}, 'complete_usage': None}}}.items():
            save(self.area / (name + '.json'), value)
        reg = read(self.area / 'registration.json')
        reg.update(stages=runner.STAGES[1:], source_recovery={
            'phase': str(self.area / 'phase.json'), 'rollout': 'unused',
            'acceptance': str(self.area / 'receipt.json'), 'original_result': str(self.area / 'old-result.json')})
        (self.area / 'registration.json').write_text(json.dumps(reg), encoding='utf-8')
        self.opened = self.opened[1:]
        result, calls, checks, _ = self.execute([outcome(n) for n in 'abc'])
        self.assertEqual('C_task_executed_semantic_review_pending', result['status'])
        self.assertEqual(['expanded_task', 'handoff'], [s['stage_id'] for s in result['stages']])
        self.assertEqual(3, calls.call_count)
        self.assertEqual(1, checks.call_count)
        self.assertEqual(6, result['usage']['complete_usage']['total_tokens'])
        self.assertIsNone(result['historical_source_usage']['complete_usage'])
        self.assertFalse((self.area / 'source_task').exists())

    def test_failed_source_acceptance_prevents_generation_and_C(self):
        result, calls, _, checkpoint = self.execute([outcome('a')], passed=False)
        self.assertEqual('stopped', result['status'])
        self.assertEqual(1, calls.call_count)
        checkpoint.assert_not_called()

    def test_interrupted_generation_preserves_known_usage_and_stops_C(self):
        result, calls, _, _ = self.execute([outcome('a'), outcome('b', complete=False)])
        self.assertEqual('stopped', result['status'])
        self.assertEqual(2, calls.call_count)
        self.assertEqual(4, result['usage']['known_usage']['total_tokens'])
        self.assertIsNone(result['usage']['complete_usage'])

    def test_started_attempt_cannot_reenter(self):
        save(self.area / 'started.json', {'failed': True})
        with patch.object(runner, 'verify_pins'), patch.object(runner, 'manifest', return_value=self.initial), \
             patch.object(runner, 'NativeRPC') as rpc, self.assertRaises(FileExistsError):
            runner.run(self.area)
        rpc.assert_not_called()

    def test_new_protocol_passes_registered_stage_budgets_to_paid_boundary(self):
        from copy import deepcopy
        stages = deepcopy(runner.STAGES)
        budget = {'max_responses':24, 'max_seconds':600, 'max_total_tokens':1500000}
        for stage in stages:
            stage['budget'] = budget
        reg = read(self.area / 'registration.json')
        reg['stages'] = stages
        (self.area / 'registration.json').write_text(json.dumps(reg), encoding='utf8')
        result, calls, _, _ = self.execute([outcome(n) for n in 'abcd'], stages=stages)
        self.assertEqual('C_task_executed_semantic_review_pending', result['status'])
        self.assertEqual([budget, None, budget, budget],
                         [c.args[2].get('phase_budget') for c in calls.call_args_list])

    def test_new_delivery_contract_stops_completed_turn_without_final(self):
        reg = read(self.area / 'registration.json')
        reg['require_final'] = True
        (self.area / 'registration.json').write_text(json.dumps(reg), encoding='utf8')
        result, calls, checks, checkpoint = self.execute([{**outcome('a'), 'finals':[]}])
        self.assertIn('task_final_delivery_missing', result['error'])
        self.assertEqual(1, calls.call_count)
        checks.assert_not_called()
        checkpoint.assert_not_called()


class RuntimeProbeTests(unittest.TestCase):
    def test_sandbox_failure_is_preserved_without_turn_start(self):
        with tempfile.TemporaryDirectory() as temp:
            server = Mock()
            server.call.side_effect = RuntimeError('sandbox denied')
            destination = Path(temp) / 'probe'
            with self.assertRaisesRegex(ValueError, 'native_task_runtime_unavailable'):
                verify_runtime(server, temp, ['py', '-3.11'], destination)
            self.assertEqual('command/exec', server.call.call_args.args[0])
            self.assertIn('sandbox denied', read(destination / 'result.json')['error'])
            self.assertEqual(0, read(destination / 'result.json')['model_calls'])

    def test_success_requires_actual_python_capabilities(self):
        with tempfile.TemporaryDirectory() as temp:
            server = Mock()
            facts = {'version': [3, 11, 9], 'sqlite_result': 7, 'unittest_available': True,
                     'executable': str(Path(temp) / 'python.exe'), 'executable_sha256': 'a' * 64}
            server.call.return_value = {'exitCode': 0, 'stdout': json.dumps(facts), 'stderr': ''}
            self.assertEqual(facts['executable'], verify_runtime(server, temp, ['py', '-3.11'],
                                                                Path(temp) / 'pass')['executable'])
            facts['unittest_available'] = False
            server.call.return_value['stdout'] = json.dumps(facts)
            with self.assertRaisesRegex(ValueError, 'native_task_runtime_unavailable'):
                verify_runtime(server, temp, ['py', '-3.11'], Path(temp) / 'fail')


if __name__ == '__main__':
    unittest.main()
