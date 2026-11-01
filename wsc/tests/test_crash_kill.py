"""Real process-kill crash tests.

Each case runs ``crash_child.py`` as a separate process that terminates itself
without unwinding, then reopens the same store and checks what recovery can and
cannot claim.  A kill is not a power-loss test: SQLite's own durability settings
still decide whether the last transaction survived, so the assertions below only
require the invariants that hold either way (no half-committed delivery, no
duplicate event, repeatable recovery).
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
from wsc import WSC, Store
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultPolicy, ResultStore

CHILD = Path(__file__).with_name('crash_child.py')
OPEN = "state IN ('prepared','blob_staged','recovery_required')"


class RealKillChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def kill(self, mode):
        done = subprocess.run([sys.executable, str(CHILD), mode, str(self.root)],
                              capture_output=True, text=True, timeout=180)
        self.assertNotEqual(0, done.returncode,
                            f'{mode}: child exited normally\n{done.stdout}\n{done.stderr}')
        return done

    def store(self):
        return WSC(Store(self.root / 'core.db', session_id='session', workspace=str(self.root)),
                   access=lambda s, k, a: True)

    def runtime(self):
        results = ResultStore(self.root / 'results', session='session', access=lambda s, k, a: True)
        return ContextRuntime(self.store(), results, policy=ResultPolicy(enabled=True),
                              durable_results=True)

    def counts(self):
        with self.store().store.connect() as db:
            def q(sql):
                return db.execute(sql).fetchone()[0]
            return dict(events=q("SELECT COUNT(*) FROM events WHERE kind='result'"),
                        delivery=q('SELECT COUNT(*) FROM wsc_context_delivery_v1'),
                        results=q('SELECT COUNT(*) FROM wsc_context_results_v1'),
                        open=q(f'SELECT COUNT(*) FROM wsc_context_intents_v1 WHERE {OPEN}'))

    def assert_settled(self, events):
        state = self.counts()
        self.assertEqual(events, state['events'])
        self.assertEqual(events, state['delivery'])
        self.assertEqual(events, state['results'])
        self.assertEqual(0, state['open'])
        return state

    def test_kill_after_commit_keeps_exactly_one_delivery(self):
        self.kill('after_commit')
        self.assert_settled(1)
        ctx = self.runtime()
        self.assertEqual(0, ctx.recover()['scanned'])
        self.assert_settled(1)

    def test_kill_after_transaction_keeps_exactly_one_delivery(self):
        self.kill('after_commit_tx')
        self.assert_settled(1)
        self.assertEqual(0, self.runtime().recover()['scanned'])

    def test_kill_before_blob_leaves_no_event_and_no_open_intent(self):
        self.kill('before_blob')
        ctx = self.runtime()
        self.assert_settled(0)
        self.assertEqual(0, ctx.recover()['scanned'])

    def test_kill_before_commit_recovers_the_commit_from_the_staged_blob(self):
        self.kill('before_commit')
        ctx = self.runtime()
        self.assert_settled(1)
        self.assertEqual(0, ctx.recover()['scanned'])

    def test_kill_after_blob_recovers_once_and_is_idempotent(self):
        self.kill('after_blob')
        ctx = self.runtime()
        self.assert_settled(1)
        with self.store().store.connect() as db:
            source = db.execute("SELECT id FROM events WHERE kind='result'").fetchone()[0]
        view = ctx.delivery(source)
        self.assertTrue(view['external'])
        self.assertIn('result_id', view)
        for _ in range(3):
            self.assertEqual(0, ctx.recover()['scanned'])
            self.assert_settled(1)

    def test_kill_during_blob_write_leaves_reclaimable_temp_file(self):
        self.kill('during_blob')
        temps = list((self.root / 'results' / 'objects').glob('.*.tmp'))
        self.assertEqual(1, len(temps))
        ctx = self.runtime()
        self.assert_settled(0)
        # A fresh temp file may belong to a concurrent writer; only aged ones go.
        self.assertEqual([], ctx.recover()['blobs'].get('temp_removed', []))
        old = time.time() - 3600
        os.utime(temps[0], (old, old))
        self.assertEqual([temps[0].name], ctx.recover()['blobs']['temp_removed'])
        self.assertFalse(temps[0].exists())

    def test_kill_during_recovery_is_repeatable(self):
        self.kill('after_blob')
        self.kill('during_recovery')
        ctx = self.runtime()
        self.assert_settled(1)
        self.assertEqual(0, ctx.recover()['scanned'])
        self.assert_settled(1)


if __name__ == '__main__':
    main()
