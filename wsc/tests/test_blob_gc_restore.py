"""Recovery reclaims orphan blobs and spares blobs an open intent still owns."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]
from wsc import WSC, Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore, ResultPolicy, ToolText

PAYLOAD = 'INFO row\n' * 4000


class Crash(BaseException):
    pass


def boom(point):
    if point == 'after_blob':
        raise Crash(point)


class RecoveryBlobChecks(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.adapter = CodexCheckpointAdapter()

    def runtime(self, fault=None):
        core = WSC(Store(self.root / 'core.db', session_id='session', workspace=str(self.root)),
                   access=lambda s, k, a: True)
        results = ResultStore(self.root / 'results', session='session', access=lambda s, k, a: True)
        return ContextRuntime(core, results, policy=ResultPolicy(enabled=True),
                              durable_results=True, fault=fault)

    def staged_result(self, ctx):
        ctx.observe(self.adapter.import_items(
            [dict(type='function_call', call_id='c1', name='f', arguments='{}')],
            thread_id='t', start_ordinal=0))
        event = self.adapter.import_items(
            [dict(type='function_call_output', call_id='c1', output=PAYLOAD)],
            thread_id='t', start_ordinal=1)[0]
        with self.assertRaises(Crash):
            ctx.record_tool_result(event, ToolText(PAYLOAD, kind='terminal_log'))

    def test_recovery_spares_the_staged_blob_and_reclaims_the_stray(self):
        staged_ctx = self.runtime(fault=boom)
        self.staged_result(staged_ctx)
        blobs = sorted(Path(staged_ctx.results.store.objects).glob('*.txt'))
        self.assertEqual(1, len(blobs))
        stray = Path(staged_ctx.results.store.objects) / ('0' * 64 + '.txt')
        stray.write_text('orphan', encoding='utf-8')

        self.runtime()
        self.assertTrue(blobs[0].exists(), 'staged blob was reclaimed')
        self.assertFalse(stray.exists(), 'orphan survived recovery')


if __name__ == '__main__':
    main()
