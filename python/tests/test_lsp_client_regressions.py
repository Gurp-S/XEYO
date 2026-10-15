import io
from types import SimpleNamespace
import pytest
from lsp.client import LspClient, LspError, _Pending
from lsp.servers import ServerSpec


def client(tmp_path):
    return LspClient(ServerSpec('python', ('unused-server',)), tmp_path)


@pytest.mark.parametrize('bad_id', ['not-a-number', [], {}, True, 1.5, '1'])
def test_response_cannot_crash_reader_or_alias_request(tmp_path, bad_id):
    c = client(tmp_path)
    pending = _Pending()
    c._pending[1] = pending
    c._dispatch({'id': bad_id, 'result': 'wrong'})
    assert c._pending[1] is pending
    assert not pending.event.is_set()
    c._dispatch({'id': 1, 'result': 'right'})
    assert pending.event.is_set() and pending.result == 'right'


def test_write_failure_releases_pending(tmp_path, monkeypatch):
    c = client(tmp_path)
    def fail(_):
        raise BrokenPipeError('closed')
    monkeypatch.setattr(c, '_send', fail)
    with pytest.raises((LspError, BrokenPipeError)):
        c.request('hover', {})
    assert c._pending == {}


def test_reader_dispatch_failure_wakes_waiters(tmp_path, monkeypatch):
    c = client(tmp_path)
    c._proc = SimpleNamespace(stdout=io.BytesIO(b'Content-Length: 2\r\n\r\n{}'))
    pending = _Pending()
    c._pending[1] = pending
    def fail(_):
        raise ValueError('malformed protocol payload')
    monkeypatch.setattr(c, '_dispatch', fail)
    c._read_loop()
    assert pending.event.is_set() and pending.error
    assert c._pending == {}
