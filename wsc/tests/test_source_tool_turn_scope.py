from pathlib import Path
from copy import deepcopy
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'experiments')]
from wsc import WSC, Store
from wsc.contracts import Event
from wsc.source_access import SnapshotSourceAccess, SourceAccessLimits
from native_source_tool_budget import BudgetResultSourceToolHandler


class SourceTurnScopeChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.allowed = True
        core = WSC(Store(root/'state.db', session_id='s', workspace=str(root)), access=lambda *a: self.allowed)
        core.ingest([Event('a', 'observation', {}, text='original')])
        self.reader = SnapshotSourceAccess(core.store, core.capture(), access=core.access,
                                          limits=SourceAccessLimits(max_calls=2))
        self.handler = BudgetResultSourceToolHandler(self.reader)

    def event(self, turn):
        return dict(id=1, method='item/tool/call', params=dict(threadId='t', turnId=turn,
            callId='reused-id', tool='WSCSource', arguments=dict(operation='read', source='s1')))

    def test_call_identity_is_scoped_to_thread_and_turn(self):
        for turn in ('u1', 'u2'):
            event = self.event(turn)
            reply = self.handler.handle(event, thread_id='t', turn_id=turn)
            self.assertTrue(reply['result']['success'])
            self.assertEqual(reply, self.handler.handle(deepcopy(event), thread_id='t', turn_id=turn))
        self.assertEqual(2, self.reader.calls)
        self.assertEqual(2, len(self.handler.trace))

    def test_new_turn_checks_permission_instead_of_replaying_old_reply(self):
        self.handler.handle(self.event('u1'), thread_id='t', turn_id='u1')
        self.allowed = False
        reply = self.handler.handle(self.event('u2'), thread_id='t', turn_id='u2')
        self.assertFalse(reply['result']['success'])
        self.assertNotIn('original', str(reply))
        self.assertEqual(2, self.reader.calls)

    def test_new_turn_does_not_reset_total_callback_budget(self):
        for turn in ('u1', 'u2', 'u3'):
            reply = self.handler.handle(self.event(turn), thread_id='t', turn_id=turn)
        self.assertFalse(reply['result']['success'])
        self.assertEqual(2, self.reader.calls)
        self.assertEqual(2, len(self.handler.seen))
        self.assertEqual(1, self.handler.refused_callbacks)


if __name__ == '__main__':
    unittest.main()
