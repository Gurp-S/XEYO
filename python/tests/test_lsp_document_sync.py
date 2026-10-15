import threading
from concurrent.futures import ThreadPoolExecutor
from lsp.client import LspClient
from lsp.servers import ServerSpec


def test_open_document_tracks_disk_changes(tmp_path, monkeypatch):
    p = tmp_path / 'a.py'
    p.write_text('old')
    c = LspClient(ServerSpec('python'), tmp_path)
    sent = []
    monkeypatch.setattr(c, 'notify', lambda method, params: sent.append((method, params)))
    uri = c.ensure_open(p, 'python')
    c.ensure_open(p, 'python')
    p.write_text('new')
    assert c.ensure_open(p, 'python') == uri
    assert [x[0] for x in sent] == ['textDocument/didOpen', 'textDocument/didChange']
    assert sent[-1][1] == {'textDocument': {'uri': uri, 'version': 2},
                            'contentChanges': [{'text': 'new'}]}


def test_concurrent_document_open_is_single_publication(tmp_path, monkeypatch):
    p = tmp_path / 'a.py'
    p.write_text('x')
    c = LspClient(ServerSpec('python'), tmp_path)
    sent = []
    first_entered, release = threading.Event(), threading.Event()
    def notify(method, params):
        sent.append(method)
        first_entered.set()
        assert release.wait(2)
    monkeypatch.setattr(c, 'notify', notify)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(c.ensure_open, p, 'python')
        assert first_entered.wait(2)
        second = pool.submit(c.ensure_open, p, 'python')
        release.set()
        assert first.result(2) == second.result(2)
    assert sent == ['textDocument/didOpen']


def test_failed_change_notification_is_retried_at_same_version(tmp_path, monkeypatch):
    import pytest
    from lsp.client import LspError
    p = tmp_path / 'a.py'
    p.write_text('old')
    c = LspClient(ServerSpec('python'), tmp_path)
    sent = []
    monkeypatch.setattr(c, 'notify', lambda m, p: sent.append((m, p)))
    c.ensure_open(p, 'python')
    p.write_text('new')
    def fail(m, p):
        raise BrokenPipeError('closed')
    monkeypatch.setattr(c, 'notify', fail)
    with pytest.raises(LspError):
        c.ensure_open(p, 'python')
    monkeypatch.setattr(c, 'notify', lambda m, p: sent.append((m, p)))
    c.ensure_open(p, 'python')
    assert sent[-1][1]['textDocument']['version'] == 2
    assert sent[-1][1]['contentChanges'] == [{'text': 'new'}]
