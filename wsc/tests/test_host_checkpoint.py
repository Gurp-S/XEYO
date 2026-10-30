"""Host-prefix retirement is evidence-bound and cannot remove later task controls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import digest, file_hash, read, save
from native_rollout_snapshot import capture_rollout
from native_host_checkpoint import HostContextAdapter, PendingHostCheckpoint
from native_message_checkpoint import prepare_message_checkpoint
from wsc import Store, WSC, WSCError
import run_control_continuation as runner


def message(role, text):
    return {'type': 'message', 'role': role, 'content': [
        {'type': 'output_text' if role == 'assistant' else 'input_text', 'text': text}]}


class HostCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = [message('developer', 'old host version'), message('user', 'project rules')]
        self.control = message('developer', 'original execution identity')
        self.tail = [self.control, message('user', 'task request'), deepcopy(self.prefix[1]),
                     message('developer', 'later task constraint'),
                     message('assistant', '{"kind":"working_state"}')]
        self.source = self.root / 'source.jsonl'
        self.write_rollout(self.source, 'source', [*self.prefix, *self.tail])
        self.phase = {'thread_id': 'source', 'rollout_sha256': file_hash(self.source), 'completed': False,
                      'failure': 'cap', 'usage_complete': False, 'usage_completion_evidence': {'turn_id': 'turn'}}
        self.reg = {'workspace': str(self.root), 'accounting_scope': 'fresh_single_turn',
                    'execution_fact': self.control}
        self.admission = self.admit('source', self.prefix, [self.control])
        self.receipt = {'observed_at': 'checked', 'source_manifest_sha256': 'fixture', 'names': ['scope'],
                        'tests': 1, 'passed': True, 'scope': 'fixture', 'grader_sha256': 'fixture'}
        self.marker = [message('assistant', 'host observation')]
        self.current = [message('developer', 'new host version'), deepcopy(self.prefix[1])]
        self.target = self.root / 'target.jsonl'
        self.write_rollout(self.target, 'target', [*self.current, *self.marker])
        self.target_admission = self.admit('target', self.current, self.marker)
        self.source_cell = self.root / 'source_task'
        save(self.source_cell / 'registration.json', self.reg)
        save(self.source_cell / 'admission.json', self.admission)

    def write_rollout(self, path, identity, items, extra=()):
        rows = [{'type': 'session_meta', 'payload': {'id': identity, 'base_instructions': 'native'}},
                {'type': 'turn_context', 'timestamp': 'observed', 'payload': {
                    'turn_id': 'turn', 'cwd': str(self.root), 'model': 'fixture'}}]
        rows += [{'type': 'response_item', 'timestamp': 'observed', 'payload': p} for p in items]
        rows += list(extra)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf8')

    def admit(self, identity, prefix, controls):
        return {'thread_id': identity, 'response_count': 0, 'controls_sha256': digest(controls),
                'prefix_sha256': digest(prefix), 'host': {'bootstrap_messages': deepcopy(prefix),
                    'base_instructions_sha256': digest('native')}}

    def adapter(self):
        return HostContextAdapter(capture_rollout(self.source), self.admission, self.reg, self.phase,
                                  capture_rollout(self.target), self.target_admission, self.marker)

    def build(self, name, adapter=None):
        return prepare_message_checkpoint(self.root / name, self.root, self.source, self.phase,
                                          self.receipt, self.root / 'receipt.json', adapter=adapter)

    def test_before_after_preserves_later_controls_and_real_publication_contract(self):
        before = self.build('baseline')
        with patch.object(WSC, 'generate', side_effect=AssertionError('generation forbidden')):
            after = self.build('candidate', self.adapter())
        self.assertEqual([*self.prefix, *self.tail], before['items'][:-1])
        self.assertEqual(self.tail, after['items'][:-1])
        self.assertEqual(digest({k:v for k,v in after.items() if k != 'package_digest'}), after['package_digest'])
        facts = json.loads(after['items'][-1]['content'][0]['text'])
        oldfacts = json.loads(before['items'][-1]['content'][0]['text'])
        self.assertEqual(oldfacts['model_records'], facts['model_records'])
        self.assertEqual(oldfacts['clues'], facts['clues'])
        # Independent builds emit their phase observation at different times.
        def observations(state):
            values = [json.loads(x['text']) for x in state['historical_excerpts']]
            for value in values:
                value.pop('observed_at', None)
            return values
        self.assertEqual(observations(oldfacts), observations(facts))
        for entry, item in zip(facts['historical_host_context']['sources'], self.prefix):
            self.assertEqual(item, read(entry['path']))
            self.assertEqual(entry['sha256'], file_hash(entry['path']))
        result = read(self.root / 'candidate/result.json')
        core = WSC(Store(self.root / 'candidate/state.db', session_id='candidate', workspace=str(self.root)),
                   access=lambda *args: True)
        self.assertEqual(after, core.package(result['operation']))
        self.assertEqual(0, result['cursor'])
        self.assertEqual([], result['usage']['attempts'])
        self.assertEqual('target', after['adapter']['host_context_binding']['target_thread_id'])

    def test_changed_source_prefix_and_ambiguous_execution_fact_rejected(self):
        self.admission['prefix_sha256'] = 'tampered'
        with self.assertRaisesRegex(WSCError, 'host_prefix_changed'):
            self.adapter()
        self.admission = self.admit('source', self.prefix, [self.control])
        self.write_rollout(self.source, 'source', [*self.prefix, *self.tail, self.control])
        self.phase['rollout_sha256'] = file_hash(self.source)
        with self.assertRaisesRegex(WSCError, 'host_execution_boundary_missing_or_ambiguous'):
            self.adapter()

    def test_source_archive_identity_and_scope_are_not_inferred(self):
        self.phase['rollout_sha256'] = 'tampered'
        with self.assertRaisesRegex(WSCError, 'host_source_archive_changed'):
            self.adapter()
        self.phase['rollout_sha256'] = file_hash(self.source)
        self.reg['accounting_scope'] = 'append_only_turn'
        with self.assertRaisesRegex(WSCError, 'host_source_scope_unsupported'):
            self.adapter()

    def test_current_user_control_requires_actual_coverage_before_publication(self):
        # The admission claims coverage, but the actual target archive differs.
        self.write_rollout(self.target, 'target', [message('developer', 'new host'), *self.marker])
        with self.assertRaisesRegex(WSCError, 'host_prefix_changed'):
            self.adapter()
        self.target_admission = self.admit('target', [message('developer', 'new host')], self.marker)
        with self.assertRaisesRegex(WSCError, 'host_user_control_coverage_missing'):
            self.adapter()
        self.assertFalse((self.root / 'candidate').exists())

    def test_target_with_later_activity_or_actual_receipt_is_not_fresh(self):
        self.write_rollout(self.target, 'target', [*self.current, *self.marker, message('user', 'later')])
        with self.assertRaisesRegex(WSCError, 'host_target_not_fresh'):
            self.adapter()
        for activity in [{'type': 'token_usage_record', 'payload': {}},
                         {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'live'}}]:
            with self.subTest(activity=activity):
                self.write_rollout(self.target, 'target', [*self.current, *self.marker], [activity])
                with self.assertRaisesRegex(WSCError, 'host_target_not_fresh'):
                    self.adapter()

    def test_user_coverage_cannot_reverse_order_or_collapse_repeated_controls(self):
        for old, current in [([message('user', 'A'), message('user', 'B')],
                              [message('user', 'B'), message('user', 'A')]),
                             ([message('user', 'A'), message('user', 'A')], [message('user', 'A')])]:
            with self.subTest(old=old, current=current):
                self.write_rollout(self.source, 'source', [*old, self.control])
                self.phase['rollout_sha256'] = file_hash(self.source)
                self.admission = self.admit('source', old, [self.control])
                self.write_rollout(self.target, 'target', [*current, *self.marker])
                self.target_admission = self.admit('target', current, self.marker)
                with self.assertRaisesRegex(WSCError, 'host_user_control_coverage_missing'):
                    self.adapter()
    def test_corrupt_cold_source_fails_publication(self):
        from wsc.evidence import export_sources
        def corrupt(*args, **kwargs):
            locators = export_sources(*args, **kwargs)
            Path(locators[self.adapter().keys[0]]['file_path']).write_text('{}', encoding='utf8')
            return locators
        with patch('wsc.evidence.export_sources', side_effect=corrupt), \
             self.assertRaisesRegex(WSCError, 'host_cold_evidence_changed'):
            self.build('candidate', self.adapter())
        self.assertFalse((self.root / 'candidate/package.json').exists())
        self.assertEqual('failed_preserved', read(self.root / 'candidate/result.json')['status'])

    def run_pending(self, *, drift=False, missing_user=False):
        area = self.root / 'run'
        area.mkdir()
        pending = PendingHostCheckpoint(area / 'checkpoint', self.root, self.source, self.phase,
                                        self.receipt, self.root / 'receipt.json', self.source_cell)
        opened = {'thread': {'id': 'target', 'path': str(self.target)}}
        calls = []
        current = self.current[:1] if missing_user else self.current
        def inject(server, value, items, cell):
            calls.append(deepcopy(items))
            if len(calls) == 1:
                self.write_rollout(self.target, 'target', [*current, *items])
        def build(*args, **kwargs):
            package = prepare_message_checkpoint(*args, **kwargs)
            if drift:
                with self.target.open('a', encoding='utf8') as stream:
                    stream.write(json.dumps({'type': 'response_item', 'payload': message('user', 'drift')})+'\n')
            return package
        with patch('run_native_pair.import_items', side_effect=inject), \
             patch('native_host_checkpoint.prepare_message_checkpoint', side_effect=build):
            if drift or missing_user:
                reason = 'host_target_changed_before_import' if drift else 'host_user_control_coverage_missing'
                with self.assertRaisesRegex(WSCError, reason):
                    pending.import_into(None, opened, area, message('developer', 'current fact'))
                self.assertEqual(1, len(calls))  # observation only, no candidate injection
            else:
                items = pending.import_into(None, opened, area, message('developer', 'current fact'))
                self.assertEqual(items, calls[1])
                self.assertEqual(self.tail, items[:-2])
                self.assertIsNone(read(area / 'host-publication.json')['installation_receipt'])
        return calls

    def test_deferred_publication_then_import(self):
        self.assertEqual(2, len(self.run_pending()))

    def test_target_changes_between_publication_and_import_stop_injection(self):
        self.run_pending(drift=True)

    def test_missing_user_coverage_stops_before_build_and_candidate_injection(self):
        self.run_pending(missing_user=True)
        self.assertFalse((self.root / 'run/checkpoint').exists())

    def test_driver_host_mode_defers_generator_and_publication(self):
        reg = {'workspace': str(self.root), 'candidate': {'checkpoint_mode': 'host_messages'}}
        with patch.object(runner, 'open_thread') as opened, patch.object(runner, 'generate_checkpoint') as gen:
            value = runner.checkpoint_phase(None, reg, self.root, {}, [], {}, self.phase,
                                             self.source, self.receipt, self.root / 'receipt.json')
        self.assertIsInstance(value, PendingHostCheckpoint)
        opened.assert_not_called()
        gen.assert_not_called()
        self.assertFalse((self.root / 'checkpoint').exists())


if __name__ == '__main__':
    unittest.main()
