"""Blocking startup work preserves runtime and cancellation contracts."""
import asyncio
import ssl
import threading

import pytest


@pytest.mark.asyncio
async def test_stop_during_probe_is_not_lost(tmp_path, monkeypatch):
    from engine.query_engine import build_default_engine
    from engine import runtime_capabilities
    from msgtypes.events import StoppedEvent, FinalEvent
    entered, release = threading.Event(), threading.Event()
    original = runtime_capabilities.probe_runtime_capabilities
    def blocked(cwd, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(cwd, **kwargs)
    monkeypatch.setattr(runtime_capabilities, "probe_runtime_capabilities", blocked)
    monkeypatch.chdir(tmp_path)
    engine = build_default_engine(model_backend="fake")
    async def consume():
        return [event async for event in engine.submit("hello")]
    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        engine.interrupt()
    finally:
        release.set()
    events = await asyncio.wait_for(task, 5)
    assert any(isinstance(e, StoppedEvent) and e.reason == "aborted" for e in events)
    assert not any(isinstance(e, FinalEvent) for e in events)


@pytest.mark.asyncio
async def test_tls_configuration_is_loaded_once_with_proxies(monkeypatch):
    import httpx
    from model.http_transport import create_client
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:8991")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8992")
    calls = []
    original = ssl.create_default_context
    def tracked(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(ssl, "create_default_context", tracked)
    client = create_client(httpx, 120)
    try:
        assert len(calls) == 1
        context = client._transport._pool._ssl_context
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        for transport in client._mounts.values():
            if transport is not None:
                assert transport._pool._ssl_context is context
    finally:
        await client.aclose()


def test_invalid_explicit_certificate_path_still_fails(monkeypatch, tmp_path):
    import httpx
    from model.http_transport import create_client
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    with pytest.raises(FileNotFoundError):
        create_client(httpx, 120)
