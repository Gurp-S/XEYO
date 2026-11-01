"""Child process for real-kill crash tests.

Builds a real runtime on a real store, then terminates the process without
unwinding (SIGKILL on POSIX, TerminateProcess on Windows) at a chosen point.
Nothing here is a mock: the parent inspects whatever the OS left on disk.
"""
import ctypes
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc import WSC, Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultPolicy, ResultStore, ToolText
from wsc.tool_results import storage as storage_module

RAW = '中文🙂\r\nINFO row\n' * 4000
CALL = 'c1'


def hard_kill():
    if os.name == 'nt':
        kernel32 = ctypes.windll.kernel32
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 1)
    else:
        import signal
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(137)


def runtime(root, fault=None):
    core = WSC(Store(root / 'core.db', session_id='session', workspace=str(root)),
               access=lambda s, k, a: True)
    results = ResultStore(root / 'results', session='session', access=lambda s, k, a: True)
    return core, results, ContextRuntime(core, results, policy=ResultPolicy(enabled=True),
                                         durable_results=True, fault=fault)


def event_and_value():
    adapter = CodexCheckpointAdapter()
    call = adapter.import_items([dict(type='function_call', call_id=CALL, name='f', arguments='{}')],
                                thread_id='t', start_ordinal=0)
    out = adapter.import_items([dict(type='function_call_output', call_id=CALL, output=RAW)],
                               thread_id='t', start_ordinal=1)[0]
    return call, out, ToolText(RAW, kind='terminal_log')


def main(argv):
    mode, root = argv[1], Path(argv[2])

    def fault(point):
        if point == mode:
            hard_kill()

    if mode == 'during_blob':
        def capture(self, call_id, text, meta):
            (Path(self.objects) / '.deadbeef.tmp').write_bytes(b'partial')
            hard_kill()
        storage_module.ResultStore.capture = capture

    core, results, ctx = runtime(root, fault)
    if mode == 'during_recovery':
        ctx.recover()
        return 0
    call, out, value = event_and_value()
    ctx.observe(call)
    ctx.record_tool_result(out, value)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
