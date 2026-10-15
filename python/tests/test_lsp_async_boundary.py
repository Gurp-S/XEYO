import threading
import pytest
from engine.abort import AbortController
from tools.lsp_tool import LspTool


@pytest.mark.asyncio
async def test_lsp_start_and_query_do_not_block_event_loop(tmp_path, monkeypatch):
    from lsp import manager
    path = tmp_path / 'a.py'
    path.write_text('x')
    loop_thread = threading.get_ident()
    threads = []
    def get_client(*args, **kwargs):
        threads.append(threading.get_ident())
        return object()
    def dispatch(*args):
        threads.append(threading.get_ident())
        return 'ok'
    monkeypatch.setattr(manager, 'client_for', get_client)
    monkeypatch.setattr(LspTool, '_dispatch', staticmethod(dispatch))
    result = await LspTool(cwd=str(tmp_path)).execute({'action': 'symbols', 'path': 'a.py'}, AbortController())
    assert result.content == 'ok'
    assert len(threads) == 2 and all(t != loop_thread for t in threads)


@pytest.mark.asyncio
async def test_cancellation_after_query_does_not_return_success(tmp_path, monkeypatch):
    from lsp import manager
    from engine.abort import Aborted
    (tmp_path / 'a.py').write_text('x')
    abort = AbortController()
    monkeypatch.setattr(manager, 'client_for', lambda *a: object())
    def dispatch(*a):
        abort.abort('user cancelled')
        return 'late success'
    monkeypatch.setattr(LspTool, '_dispatch', staticmethod(dispatch))
    with pytest.raises(Aborted):
        await LspTool(cwd=str(tmp_path)).execute({'action': 'symbols', 'path': 'a.py'}, abort)
