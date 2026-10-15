import threading
from concurrent.futures import ThreadPoolExecutor
from lsp import manager
from lsp.servers import ServerSpec


def test_concurrent_start_does_not_leak_or_duplicate_cache(tmp_path, monkeypatch):
    manager.shutdown_all()
    barrier = threading.Barrier(2)
    created = []
    class Fake:
        def __init__(self, *a, **kw):
            self.stopped = False
            created.append(self)
        def start(self):
            barrier.wait(timeout=2)
        def stop(self):
            self.stopped = True
    monkeypatch.setattr(manager, 'find_server', lambda _: ServerSpec('python'))
    monkeypatch.setattr(manager, 'LspClient', Fake)
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(manager.client_for, tmp_path, 'python') for _ in range(2)]
            clients = [f.result(3) for f in futures]
        assert clients[0] is clients[1]
        assert len(manager._order) == 1
        assert sum(not c.stopped for c in created) == 1
    finally:
        manager.shutdown_all()


def test_shutdown_during_start_does_not_resurrect_client(tmp_path, monkeypatch):
    manager.shutdown_all()
    entered, release = threading.Event(), threading.Event()
    created = []
    class Fake:
        def __init__(self, *a, **kw):
            self.stopped = False
            created.append(self)
        def start(self):
            entered.set()
            assert release.wait(2)
        def stop(self):
            self.stopped = True
    monkeypatch.setattr(manager, 'find_server', lambda _: ServerSpec('python'))
    monkeypatch.setattr(manager, 'LspClient', Fake)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(manager.client_for, tmp_path, 'python')
        assert entered.wait(2)
        manager.shutdown_all()
        release.set()
        result = future.result(3)
    try:
        assert result is None
        assert not manager._clients and not manager._order
        assert created[0].stopped
    finally:
        manager.shutdown_all()
