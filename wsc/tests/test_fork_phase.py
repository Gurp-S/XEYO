"""Registered fork inheritance must not become newly billed work."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import manifest
from native_execution_binding import report_execution_item, verify_execution_binding
from native_fork_phase import fork_baseline, account_fork_turn
from native_turn_accounting import account_turn
import test_native_turn_accounting as fixture


class ForkPhaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.root / 'frozen-workspace').mkdir()
        self.parent = self.root / 'parent.jsonl'
        self.child = self.root / 'child.jsonl'
        self.item = report_execution_item(self.workspace, manifest(self.workspace))
        parent_paid = fixture.paid('parent-response', 'old', 1, 10)
        parent_paid['payload']['thread_id'] = 'parent'
        self.parent_rows = [{'type': 'session_meta', 'payload': {'id': 'parent'}},
                            parent_paid, fixture.count(8),
                            {'type': 'compacted', 'payload': {'replacement_history': [self.item]}}]
        parent_raw = fixture.raw(self.parent_rows)
        self.parent.write_bytes(parent_raw)
        base = {'thread_id': 'parent', 'end_byte_offset': len(parent_raw),
                'end_ordinal_exclusive': len(self.parent_rows)}
        self.before = [{'type': 'session_meta', 'payload': {
            'id': 'thread', 'forked_from_id': 'parent', 'history_mode': 'paginated',
            'forked_from_ordinal_exclusive': len(self.parent_rows), 'history_base': base}},
            fixture.event('thread_settings_applied', thread_id='thread', thread_settings={
                'cwd': str(self.workspace), 'model': 'fixture-model', 'reasoning_effort': 'max'}),
            {'type': 'response_item', 'payload': self.item}]
        self.binding = {'parent': {**base, 'path': str(self.parent),
                        'prefix_sha256': sha256(parent_raw).hexdigest()}}
        self.refresh()
        self.delta = [fixture.event('task_started', turn_id='new'),
                      fixture.paid('new-response', 'new', 1, 11), fixture.count(9),
                      fixture.event('task_complete', turn_id='new')]
        self.reg = {'purpose': 'comparison', 'accounting_scope': 'fork_append_only_turn',
                    'fork_history_binding': self.binding, 'execution_fact': self.item,
                    'workspace': str(self.workspace), 'model': 'fixture-model', 'effort': 'max',
                    'origin': str(self.root), 'initial_manifest': {}, 'pins': {}, 'shared_request': 'fixture'}
        self.opened = {'thread': {'id': 'thread', 'path': str(self.child)},
                       'cwd': str(self.workspace), 'model': 'fixture-model', 'reasoningEffort': 'max'}

    def refresh(self):
        raw = fixture.raw(self.before)
        self.child.write_bytes(raw)
        self.binding['child_sha256'] = sha256(raw).hexdigest()

    def proof(self, delta=None, turn='new'):
        return account_fork_turn(fixture.raw(self.before), fixture.raw(self.before + (
            self.delta if delta is None else delta)), binding=self.binding, thread_id='thread', turn_id=turn)

    def test_first_turn_uses_two_distinct_inherited_counters(self):
        old = account_turn(fixture.raw(self.before), fixture.raw(self.before + self.delta),
                           thread_id='thread', turn_id='new')
        new = self.proof()
        self.assertFalse(old['complete'])
        self.assertTrue(new['complete'], new['reasons'])
        self.assertEqual(12, new['complete_usage']['total_tokens'])
        self.assertEqual(120, new['inherited_thread_counter']['total_tokens'])
        self.assertEqual(96, new['display_counter_baseline']['total_tokens'])
        self.assertEqual(1, new['receipts']['response_count'])

    def test_missing_receipt_or_wrong_counter_retains_unknown_total(self):
        for mode in ('missing', 'counter'):
            rows = deepcopy(self.delta)
            if mode == 'missing':
                del rows[1]
            else:
                rows[1]['payload']['thread_token_usage'] = fixture.amount(20)
            out = self.proof(rows)
            self.assertFalse(out['complete'])
            self.assertIsNone(out['complete_usage'])
            self.assertEqual(0 if mode == 'missing' else 12, out['known_usage']['total_tokens'])

    def test_parent_response_cannot_be_rebilled(self):
        rows = deepcopy(self.delta)
        rows[1]['payload']['response_id'] = 'parent-response'
        out = self.proof(rows)
        self.assertIn('turn_response_reused_from_history', out['reasons'])
        self.assertEqual(0, out['receipts']['response_count'])

    def test_following_turn_uses_latest_local_counters(self):
        self.before += self.delta
        self.refresh()
        next_rows = [fixture.event('task_started', turn_id='next'),
                     fixture.paid('next-response', 'next', 1, 12), fixture.count(10),
                     fixture.event('task_complete', turn_id='next')]
        out = self.proof(next_rows, turn='next')
        self.assertTrue(out['complete'], out['reasons'])
        self.assertEqual(12, out['complete_usage']['total_tokens'])
        self.assertEqual(132, out['inherited_thread_counter']['total_tokens'])
        self.assertEqual(108, out['display_counter_baseline']['total_tokens'])

    def test_changed_parent_is_rejected_before_inference(self):
        self.parent.write_bytes(self.parent.read_bytes().replace(b'parent-response', b'parent-changed!'))
        with self.assertRaisesRegex(ValueError, 'parent_prefix_changed'):
            fork_baseline(fixture.raw(self.before), self.binding, thread_id='thread')

    def test_current_local_fact_and_actual_workspace_required(self):
        verify_execution_binding(self.reg, self.opened)
        self.before.pop()  # Same fact still exists in inherited compaction.
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'execution_fact_not_local'):
            verify_execution_binding(self.reg, self.opened)
        self.before.append({'type': 'response_item', 'payload': self.item})
        self.refresh()
        (self.workspace / 'changed.txt').write_text('changed', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'workspace_manifest_changed'):
            verify_execution_binding(self.reg, self.opened)

    def run_phase(self, *, mutate_parent=False):
        from run_native_pair import phase
        cell = self.root / 'phase'
        cell.mkdir()
        after = fixture.raw(self.before + self.delta)
        path = self.child
        calls = []
        parent = self.parent

        class Server:
            def __init__(self):
                self.events = iter([
                    {'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thread'}},
                    {'method': 'turn/completed', 'params': {'threadId': 'thread',
                     'turn': {'id': 'new', 'status': 'completed'}}}])

            def call(self, method, params):
                calls.append((method, params))
                if method != 'turn/start':
                    raise AssertionError('unexpected interrupt')
                path.write_bytes(after)
                if mutate_parent:
                    parent.write_bytes(parent.read_bytes().replace(b'parent-response', b'parent-changed!'))
                return {'turn': {'id': 'new'}}

            def event(self, **kwargs):
                return next(self.events)

        result = phase(Server(), self.opened, self.reg, cell, None, time.monotonic() + 10)
        return result, calls, cell

    def test_shared_phase_admits_fork_counts_new_receipts_and_materializes_history(self):
        result, calls, cell = self.run_phase()
        self.assertTrue(result['usage_complete'], result)
        self.assertIsNone(result['failure'])
        self.assertEqual(12, result['receipts']['all_usage']['total_tokens'])
        self.assertEqual('fixture-model', calls[0][1]['model'])
        canonical = json.loads((cell / 'canonical-state.json').read_text(encoding='utf8'))
        self.assertEqual([self.item, self.item], canonical['items'])
        self.assertEqual(4, canonical['inherited_history_evidence']['inherited_records'])

    def test_parent_changes_during_execution_preserve_paid_receipts_and_fail_closed(self):
        result, _, cell = self.run_phase(mutate_parent=True)
        self.assertFalse(result['usage_complete'])
        self.assertEqual(12, result['receipts']['all_usage']['total_tokens'])
        self.assertIn('parent_prefix_changed', result['accounting_error'])
        self.assertFalse((cell / 'canonical-state.json').exists())


if __name__ == '__main__':
    unittest.main()
