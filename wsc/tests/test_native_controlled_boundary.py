from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_controlled_boundary import assess_wait, seal_controlled_stop
from native_evidence import FIELDS


def raw(rows):
    return ''.join(json.dumps(row) + '\n' for row in rows).encode()


class ControlledBoundaryChecks(unittest.TestCase):
    def setUp(self):
        self.value = dict.fromkeys(FIELDS, 0)
        self.value.update(input_tokens=20, cached_input_tokens=10, output_tokens=2, total_tokens=22)
        self.callback = dict(id=9, method='item/tool/call', params=dict(threadId='t', turnId='u',
            callId='inner', tool='checkpoint_ready', arguments={}))
        self.rows = [dict(type='session_meta', payload=dict(id='t')),
            dict(type='event_msg', payload=dict(type='task_started', turn_id='u')),
            dict(type='response_item', payload=dict(type='custom_tool_call', name='exec', call_id='outer',
                input='const r = await tools.checkpoint_ready({});\ntext(r);\n')),
            dict(type='token_usage_record', payload=dict(thread_id='t', turn_id='u', response_id='r',
                usage=self.value, turn_token_usage=self.value, thread_token_usage=self.value))]
        self.events = [dict(method='turn/started', params=dict(threadId='t', turn=dict(id='u'))),
            dict(method='item/started', params=dict(threadId='t', turnId='u', item=dict(type='dynamicToolCall',
                id='inner', tool='checkpoint_ready'))), self.callback]
        self.tail = [dict(type='response_item', payload=dict(type='custom_tool_call_output', call_id='outer', output='aborted by user after 2s')),
            dict(type='event_msg', payload=dict(type='turn_aborted', turn_id='u', reason='interrupted')),
            dict(type='event_msg', payload=dict(type='item_completed', turn_id='u', item=dict(type='DynamicToolCall',
                id='inner', status='failed', success=False, error='dynamic tool call was cancelled before receiving a response')))]
        self.cleanup = dict(root_pids=[42], members_after_termination=[], empty_confirmed=True)

    def gate(self, members=(42,)):
        return assess_wait(raw(self.rows), self.callback, self.events, root_pid=42, owned_members=members)

    def seal(self):
        return seal_controlled_stop(self.gate(), raw(self.rows), raw(self.rows + self.tail), self.cleanup)

    def test_stop_seal_is_not_task_completion_or_checkpoint_publication(self):
        self.assertTrue(self.gate().admitted)
        proof = self.seal()
        self.assertEqual(22, proof.receipts['all_usage']['total_tokens'])
        from native_controlled_boundary import stop_event
        self.assertFalse(stop_event(proof).payload['task_completion_observed'])
        self.assertFalse(hasattr(proof, 'checkpoint_committed'))
        self.assertFalse(hasattr(proof, 'receiver_installed'))

    def test_missing_or_additional_owned_processes_reject_boundary(self):
        for members in (None, (), (42, 43)):
            self.assertFalse(self.gate(members).admitted)

    def test_concurrent_command_rejects_even_with_settled_model_receipt(self):
        self.events.insert(1, dict(method='item/started', params=dict(threadId='t', turnId='u',
            item=dict(type='commandExecution', id='writing'))))
        self.assertIn('operations_not_drained', self.gate().reasons)

    def test_second_model_call_in_response_is_not_exclusive_checkpoint(self):
        self.rows.insert(-1, dict(type='response_item', payload=dict(type='function_call', call_id='other', name='write')))
        self.assertFalse(self.gate().admitted)

    def test_exec_with_other_code_is_not_exclusive_checkpoint(self):
        self.rows[2]['payload']['input'] += 'await tools.exec_command({cmd:"write"});'
        self.assertIn('checkpoint_not_exclusive_exec', self.gate().reasons)

    def test_foreign_execution_and_inconsistent_receipt_reject(self):
        self.events.append(dict(method='turn/started', params=dict(threadId='t', turn=dict(id='other'))))
        self.assertIn('foreign_execution_event', self.gate().reasons)
        self.events.pop()
        self.rows.append(dict(type='event_msg', payload=dict(type='task_started', turn_id='other')))
        self.assertIn('other_execution_started', self.gate().reasons)
        self.rows.pop()
        self.value['cached_input_tokens'] = 21
        self.assertIn('response_usage_inconsistent', self.gate().reasons)

    def test_missing_receipt_or_new_unreceipted_model_output_rejects(self):
        receipt = self.rows.pop()
        self.assertFalse(self.gate().admitted)
        self.rows.append(receipt)
        self.rows.append(dict(type='response_item', payload=dict(type='reasoning')))
        self.assertIn('unreceipted_model_output', self.gate().reasons)

    def test_compaction_replacement_is_not_controlled_stop(self):
        self.tail[1]['payload']['reason'] = 'replaced'
        self.tail.append(dict(type='event_msg', payload=dict(type='task_started', turn_id='new-compaction')))
        with self.assertRaisesRegex(ValueError, 'extra_execution'):
            self.seal()

    def test_new_provider_receipt_is_not_dropped_or_called_complete(self):
        late = deepcopy(self.rows[-1]); late['payload']['response_id'] = 'late'
        self.tail.append(late)
        with self.assertRaisesRegex(ValueError, 'late_or_changed_receipts'):
            self.seal()

    def test_new_control_message_requires_reassessment(self):
        self.tail.append(dict(type='response_item', payload=dict(type='message', role='user', content=[])))
        with self.assertRaisesRegex(ValueError, 'new_model_or_control'):
            self.seal()

    def test_missing_cancel_ack_is_not_inferred_from_abort_text(self):
        self.tail.pop()
        with self.assertRaisesRegex(ValueError, 'unanswered_callback'):
            self.seal()

    def test_cancelled_call_still_needs_actual_paired_source_result(self):
        self.tail.pop(0)
        with self.assertRaisesRegex(ValueError, 'calls_unpaired'):
            self.seal()

    def test_cleanup_must_confirm_matching_owned_root_empty(self):
        self.cleanup['members_after_termination'] = [43]
        with self.assertRaisesRegex(ValueError, 'processes_not_closed'):
            self.seal()


class CommittedReceiverChecks(unittest.TestCase):
    """Offline WSC publication fixture, not a native installation proof."""
    def setUp(self):
        from wsc import WSC, Store, Selection
        from wsc.adapters.codex import CodexCheckpointAdapter
        from native_controlled_boundary import stop_event
        from native_application_budget import StudyBudget
        fixture = ControlledBoundaryChecks()
        fixture.setUp()
        self.sealed = fixture.seal()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.core = WSC(Store(root / 'state.db', session_id='fixture', workspace=str(root)),
                        access=lambda *args: True)
        marker = stop_event(self.sealed)
        self.core.ingest([marker])
        view = self.core.prepare(self.core.capture(), Selection(source_ids=(marker.id,)), producer='fixture')
        self.op = self.core.stage(view, directory=root / 'exports', adapter=CodexCheckpointAdapter())
        self.package = self.core.package(self.op)
        self.receiver = [dict(type='session_meta', payload=dict(id='receiver'))] + [
            dict(type='response_item', payload=item) for item in self.package['items']]
        self.limits = dict(max_total_tokens=100, max_responses=4, max_seconds=60)
        self.budget = StudyBudget({'B': self.limits, 'C': self.limits},
            dict(max_total_tokens=200, max_responses=8, max_seconds=120), clock=lambda: 0.)

    def host(self, lost=False):
        from wsc.adapters.callback import CallbackHost
        from wsc.contracts import HostReceipt
        def commit(p):
            if lost:
                raise TimeoutError('fixture lost reply')
            b = p['binding']
            return HostReceipt(p['operation_id'], p['package_digest'], b['session_id'], b['workspace'],
                p['next_generation'], b['control_epoch'], p['through'], 'receiver', True)
        return CallbackHost(commit=commit, lookup=lambda key: None)

    def reserve(self):
        from native_controlled_boundary import reserve_committed_receiver
        return reserve_committed_receiver(self.core, self.op, 'receiver', raw(self.receiver),
            self.sealed, self.budget, 'C', self.limits)

    def test_ready_and_lost_reply_do_not_reserve_budget(self):
        for lost in (False, True):
            if lost:
                with self.assertRaises(TimeoutError):
                    self.core.install(self.op, self.host(lost=True))
            with self.assertRaisesRegex(ValueError, 'publication_unconfirmed'):
                self.reserve()
            self.assertEqual({}, self.budget.snapshot()['inflight'])

    def test_confirmed_exact_idle_receiver_uses_existing_budget(self):
        self.core.install(self.op, self.host())
        self.budget.reserve('B', self.limits)
        ticket, granted = self.reserve()
        self.assertEqual(self.limits, granted)
        self.assertEqual('C', self.budget.snapshot()['inflight'][ticket]['arm'])
        self.assertEqual(2, len(self.budget.snapshot()['inflight']))

    def test_receipt_without_actual_import_rejects(self):
        self.core.install(self.op, self.host())
        self.receiver.pop()
        with self.assertRaisesRegex(ValueError, 'import_not_exact_suffix'):
            self.reserve()
        self.assertEqual({}, self.budget.snapshot()['inflight'])

    def test_started_receiver_rejects(self):
        self.core.install(self.op, self.host())
        self.receiver.append(dict(type='event_msg', payload=dict(type='task_started', turn_id='new')))
        with self.assertRaisesRegex(ValueError, 'receiver_not_idle'):
            self.reserve()

    def test_uncovered_source_tail_rejects(self):
        from wsc.contracts import Event
        self.core.install(self.op, self.host())
        self.core.ingest([Event('new', 'observation', dict(value='new source'))])
        with self.assertRaisesRegex(ValueError, 'uncovered_tail'):
            self.reserve()

    def test_same_arm_inflight_and_unknown_usage_reject(self):
        self.core.install(self.op, self.host())
        self.budget.reserve('C', self.limits)
        with self.assertRaisesRegex(ValueError, 'budget_unsettled'):
            self.reserve()
        self.budget.mark_unknown('C')
        with self.assertRaisesRegex(ValueError, 'budget_unsettled'):
            self.reserve()


if __name__ == '__main__':
    unittest.main()
