"""Host-contract unit checks; no native process, inference, or capacity claim."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'experiments')]
from wsc import WSC, Store
from wsc.contracts import Event
from wsc.snapshot_literal_access import SnapshotLiteralAccess
from wsc.source_access import SourceAccessLimits
from native_source_tool import SOURCE_TOOL
from native_task_recovery import open_task_receiver


class FakeSession:
    def __init__(self, workspace):
        self.registration = {'workspace': str(workspace)}
        self.opened = {'thread': {'id': 'task-thread'}}
        self.server, self.closed, self.calls = object(), False, []

    def execute_stage(self, request, destination, limits, record_phase, *, output_schema, tool_handler):
        self.calls.append(dict(request=request, destination=destination, limits=limits,
                               output_schema=output_schema, tool_handler=tool_handler))
        turn = 'turn-' + str(len(self.calls))
        event = dict(id=1, method='item/tool/call', params=dict(threadId='task-thread', turnId=turn,
            callId='same-local-id', tool='WSCSource', arguments=dict(operation='read', source='s1')))
        reply = tool_handler.handle(event, thread_id='task-thread', turn_id=turn)
        record_phase(reply)
        return reply

    def close(self):
        self.closed = True
        return {'closed': True}


class OrdinaryTaskRecoveryChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        core = WSC(Store(root/'state.db', session_id='s', workspace=str(root)), access=lambda *a: True)
        core.ingest([Event('a', 'observation', {}, text='historical original')])
        self.reader = SnapshotLiteralAccess(core.store, core.capture(), access=core.access,
                                            limits=SourceAccessLimits(max_calls=2))
        self.session = FakeSession(root)
        self.registrations = []
        def factory(**kwargs):
            self.registrations.append(kwargs)
            return self.session
        self.factory = factory
        self.port = open_task_receiver(factory, self.reader)

    def execute(self, **kwargs):
        return self.port.execute_stage('task', Path('unused'), {'response_cap': 4}, lambda value: None, **kwargs)

    def test_registration_keeps_ordinary_runtime_and_original_schema(self):
        registration = self.registrations[0]
        self.assertIsNone(registration['selector_runtime'])
        definition = registration['dynamic_tools'][0]
        self.assertEqual(SOURCE_TOOL['inputSchema'], definition['inputSchema'])
        self.assertTrue(definition['description'].endswith('prefix cut: 1.'))
        self.assertNotIn('prefix cut:', SOURCE_TOOL['description'])
        self.assertEqual([], self.session.calls)
        self.assertEqual(0, self.reader.calls)

    def test_unknown_or_denied_capacity_never_executes(self):
        with self.assertRaisesRegex(ValueError, 'capacity_unverified'):
            self.execute()
        for decision in (False, None, 1):
            with self.assertRaisesRegex(ValueError, 'capacity_not_admitted'):
                self.execute(capacity_check=lambda *a: decision)
        self.assertEqual([], self.session.calls)
        self.assertEqual(0, self.reader.calls)

    def test_dispatch_reuses_reader_and_cumulative_budget_across_turns(self):
        # These grants are test stubs, not native capacity evidence.
        for index in range(3):
            reply = self.execute(capacity_check=lambda *a: True)
            self.assertEqual(index < 2, reply['result']['success'])
        self.assertEqual(2, self.reader.calls)
        self.assertEqual(2, len(self.port.handler.trace))
        self.assertEqual(1, self.port.handler.refused_callbacks)
        self.assertEqual(1, len(self.registrations))
        self.assertIs(self.port.handler, self.session.calls[0]['tool_handler'])
        self.assertIs(self.session.calls[0]['tool_handler'], self.session.calls[1]['tool_handler'])

    def test_request_schema_and_limits_are_passed_unchanged(self):
        request, area, limits, schema = 'task', Path('unused'), {'max_responses': 4}, {'type': 'object'}
        observed = []
        self.port.execute_stage(request, area, limits, observed.append, output_schema=schema,
                                capacity_check=lambda *a: True)
        call = self.session.calls[0]
        self.assertEqual(request, call['request'])
        self.assertEqual(area, call['destination'])
        self.assertIs(limits, call['limits'])
        self.assertIs(schema, call['output_schema'])
        self.assertEqual(1, len(observed))

    def test_closed_session_rejects_stage_and_callback_without_io(self):
        self.assertEqual({'closed': True}, self.port.close())
        with self.assertRaisesRegex(ValueError, 'session_not_live'):
            self.execute(capacity_check=lambda *a: True)
        with self.assertRaisesRegex(ValueError, 'session_not_live'):
            self.port.handler.handle({}, thread_id='task-thread', turn_id='turn-1')
        self.assertEqual(0, self.reader.calls)

    def test_owner_change_during_admission_rejects_before_dispatch(self):
        def changed(*args):
            self.session.opened['thread']['id'] = 'other'
            return True
        with self.assertRaisesRegex(ValueError, 'owner_changed'):
            self.execute(capacity_check=changed)
        self.assertEqual([], self.session.calls)
        self.assertEqual(0, self.reader.calls)

    def test_wrong_callback_owner_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'owner_changed'):
            self.port.handler.handle({}, thread_id='other', turn_id='turn-1')
        self.assertEqual(0, self.reader.calls)

    def test_post_open_binding_failure_closes_session(self):
        self.session.registration['workspace'] = str(self.reader.store.path.parent/'other')
        with self.assertRaisesRegex(ValueError, 'workspace_mismatch'):
            open_task_receiver(self.factory, self.reader)
        self.assertTrue(self.session.closed)

    def test_invalid_reader_never_opens_actor(self):
        count = len(self.registrations)
        with self.assertRaisesRegex(ValueError, 'reader_invalid'):
            open_task_receiver(self.factory, object())
        self.assertEqual(count, len(self.registrations))


if __name__ == '__main__':
    unittest.main()
