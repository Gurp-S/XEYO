"""Original-message checkpoints have no paid selection stage or rewritten claims."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_message_checkpoint import prepare_message_checkpoint
from native_evidence import file_hash, read
from wsc import Store, WSC, WSCError
import run_control_continuation as runner


class MessageCheckpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.messages = [
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Earlier scope'}]},
            {'type': 'message', 'role': 'assistant', 'phase': 'commentary',
             'content': [{'type': 'output_text', 'text': 'Historical hypothesis; not confirmed.'}]},
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Expanded scope'}]}]
        self.result = {'type': 'function_call_output', 'call_id': 'read', 'output': 'Historical evidence \ufffd \U0001f50d'}
        rows = [{'type': 'session_meta', 'payload': {'id': 'fixture'}},
                {'type': 'turn_context', 'timestamp': 'original', 'payload': {'turn_id': 'turn', 'cwd': str(self.root)}}]
        items = [*self.messages[:2], {'type': 'function_call', 'call_id': 'read', 'name': 'read', 'arguments': '{}'},
                 self.result, self.messages[-1]]
        rows += [{'type': 'response_item', 'timestamp': 'original', 'payload': item} for item in items]
        self.raw = self.root / 'source.jsonl'
        self.raw.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        self.phase = {'thread_id': 'fixture', 'rollout_sha256': file_hash(self.raw), 'completed': False,
                      'failure': 'registered_response_cap', 'usage_complete': False,
                      'usage_completion_evidence': {'turn_id': 'turn'}}
        self.receipt = {'observed_at': 'checked', 'source_manifest_sha256': 'fixture-manifest',
                        'names': ['prior_scope'], 'tests': 1, 'passed': True, 'scope': 'fixture_only',
                        'grader_sha256': 'fixture'}

    def build(self):
        return prepare_message_checkpoint(self.root / 'checkpoint', self.root, self.raw, self.phase,
                                          self.receipt, self.root / 'receipt.json')

    def test_messages_exact_order_tool_cold_observations_exact_no_generation(self):
        with patch.object(WSC, 'generate', side_effect=AssertionError('unexpected generation')):
            package = self.build()
        self.assertEqual(self.messages, package['items'][:3])
        core = WSC(Store(self.root / 'checkpoint/state.db', session_id='checkpoint', workspace=str(self.root)),
                   access=lambda *args: True)
        snap = core.capture()
        tool = next(row for row in snap.events if row['kind'] == 'result')
        self.assertEqual(self.result, json.loads(core.read(tool['id'])['content']))
        result = read(self.root / 'checkpoint/result.json')
        self.assertEqual(0, result['generation_calls'])
        self.assertEqual([], result['usage']['attempts'])
        self.assertEqual(0, result['cursor'])
        self.assertEqual(7, result['source_count'])
        self.assertEqual(5, result['selected_sources'])
        state = json.loads(package['items'][3]['content'][0]['text'])
        observations = [json.loads(row['text']) for row in state['historical_excerpts']]
        self.assertEqual(['prior_scope'], observations[0]['names'])
        self.assertFalse(observations[1]['host_phase_completed'])
        self.assertFalse(observations[1]['usage_complete'])
        self.assertEqual([], state.get('model_records', []))

    def test_current_cap_rejects_oversized_messages_without_truncation_or_usage(self):
        text = self.raw.read_text(encoding='utf-8').replace('Earlier scope', 'x' * 270000)
        self.raw.write_text(text, encoding='utf-8')
        self.phase['rollout_sha256'] = file_hash(self.raw)
        with self.assertRaisesRegex(WSCError, 'view_byte_budget_exhausted'):
            self.build()
        result = read(self.root / 'checkpoint/result.json')
        self.assertEqual([], result['usage']['attempts'])
        self.assertFalse((self.root / 'checkpoint/package.json').exists())

    def test_changed_source_archive_is_rejected(self):
        self.raw.write_text(self.raw.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with self.assertRaisesRegex(WSCError, 'checkpoint_source_changed'):
            self.build()

    def test_driver_does_not_open_generator_or_add_paid_phase(self):
        phases, opened = [], {}
        reg = {'workspace': str(self.root), 'candidate': {'checkpoint_mode': 'messages'}}
        with patch.object(runner, 'open_thread') as open_thread, \
             patch.object(runner, 'generate_checkpoint') as generate, \
             patch.object(runner, 'prepare_message_checkpoint', return_value={'items': []}) as prepare:
            result = runner.checkpoint_phase(None, reg, self.root, opened, phases, {}, {}, 'rollout', {}, 'receipt')
        prepare.assert_called_once()
        open_thread.assert_not_called()
        generate.assert_not_called()
        self.assertEqual({'items': []}, result)
        self.assertEqual([], phases)
        self.assertEqual({}, opened)
        self.assertFalse((self.root / 'generation').exists())

    def test_message_route_keeps_source_identity_checks_without_scope_generation(self):
        self.phase['thread_id'] = 'wrong-thread'
        with self.assertRaisesRegex(WSCError, 'checkpoint_source_thread_mismatch'):
            self.build()
        self.assertFalse((self.root / 'checkpoint/state.db').exists())


if __name__ == '__main__':
    unittest.main()
