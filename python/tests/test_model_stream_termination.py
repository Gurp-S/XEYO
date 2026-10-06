"""Request cancellation and completion evidence, through real provider adapters."""
import asyncio
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from engine.abort import AbortController, Aborted
from engine.model_events import ModelProtocolError
from common.errors import NetworkError


def _adapter(name):
    module = importlib.import_module(f"model.{name}")
    cls = getattr(module, {"openai_compat": "OpenAICompatClient",
                           "deepseek": "DeepSeekModelClient", "anthropic": "AnthropicModelClient"}[name])
    return module, cls(api_key="offline-test", base_url="http://offline.invalid", model="probe")


class _Response:
    headers = {}

    def __init__(self, lines=(), phase=None):
        self.lines, self.phase = lines, phase
        self.status_code = 500 if phase == "error_body" else 200
        self.waiting = asyncio.Event()
        self.closed = False
        self.cancelled_wait = False

    async def _wait(self):
        self.waiting.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled_wait = True
            raise

    async def __aenter__(self):
        if self.phase == "connect": await self._wait()
        return self

    async def __aexit__(self, *args): self.closed = True
    async def aread(self): return await self._wait()

    async def aiter_lines(self):
        for line in self.lines: yield line
        if self.phase == "read": await self._wait()


def _install(monkeypatch, module, response):
    class Client:
        def stream(self, *args, **kwargs): return response
    monkeypatch.setattr(module, "get_shared_httpx_client", lambda timeout: Client())


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["openai_compat", "deepseek", "anthropic"])
@pytest.mark.parametrize("phase", ["connect", "read", "error_body"])
async def test_stop_interrupts_silent_request_io(monkeypatch, name, phase):
    module, model = _adapter(name)
    response = _Response(phase=phase)
    _install(monkeypatch, module, response)
    abort = AbortController()

    async def consume(): return [chunk async for chunk in model.stream([], [], abort)]
    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(response.waiting.wait(), 1)
        # Simulate the GUI's synchronous interrupt route in another thread.
        await asyncio.to_thread(abort.abort)
        with pytest.raises(Aborted):
            await asyncio.wait_for(task, 1)
        assert response.cancelled_wait
        assert response.closed is (phase != "connect")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["openai_compat", "deepseek"])
@pytest.mark.parametrize("ending,valid", [("both", True), ("done", True), ("reason", True),
                                        ("empty", True), ("eof", False), ("length", False)])
async def test_completion_marker_compatibility(monkeypatch, name, ending, valid):
    module, model = _adapter(name)
    lines = [] if ending == "empty" else ["data: " + json.dumps({"choices": [{"delta": {"content": "answer"}}]})]
    if ending in {"both", "reason", "length"}:
        lines.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "length" if ending == "length" else "stop"}]}))
    if ending in {"both", "done", "length"}: lines.append("data: [DONE]")
    _install(monkeypatch, module, _Response(lines))
    if valid:
        chunks = [c async for c in model.stream([], [], AbortController())]
        assert len(chunks) == (0 if ending == "empty" else 1)
    else:
        with pytest.raises(ModelProtocolError):
            _ = [c async for c in model.stream([], [], AbortController())]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["openai_compat", "deepseek", "anthropic"])
async def test_stdlib_stop_closes_active_response(monkeypatch, name):
    module, model = _adapter(name)
    started, closed = threading.Event(), threading.Event()

    class Response:
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): closed.set()
        def close(self): closed.set()
        def readline(self):
            started.set()
            if not closed.wait(2): raise AssertionError("read was not closed")
            return b""

    monkeypatch.setattr(module, "httpx", None)
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())
    abort = AbortController()
    async def consume(): return [c async for c in model.stream([], [], abort)]
    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        abort.abort()
        with pytest.raises(Aborted): await asyncio.wait_for(task, 1)
        assert closed.is_set()
    finally:
        closed.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stdlib_stop_wakes_real_local_socket_read(monkeypatch):
    module, model = _adapter("openai_compat")
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
            self.wfile.flush()
            release.wait(3)
            self.close_connection = True

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    model._base_url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(module, "httpx", None)
    abort, seen = AbortController(), asyncio.Event()

    async def consume():
        async for chunk in model.stream([], [], abort): seen.set()

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(seen.wait(), 1)
        # The next response read is silent; no more bytes are sent by the server.
        abort.abort()
        with pytest.raises(Aborted): await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["openai_compat", "deepseek"])
async def test_stdlib_usage_survives_disconnect(monkeypatch, name):
    module, model = _adapter(name)
    usage = {"prompt_tokens": 100, "completion_tokens": 10}
    lines = iter([
        b'data: {"choices":[{"delta":{"content":"partial"}}]}\n',
        ("data: " + json.dumps({"choices": [], "usage": usage}) + "\n").encode(),
    ])

    class Response:
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def close(self): pass
        def readline(self):
            try: return next(lines)
            except StopIteration: raise NetworkError("injected disconnect")

    monkeypatch.setattr(module, "httpx", None)
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())
    recorded = []
    monkeypatch.setattr(model, "_record_usage_safe", recorded.append)
    with pytest.raises(NetworkError):
        _ = [c async for c in model.stream([], [], AbortController())]
    assert model.last_usage == usage and recorded == [usage]


@pytest.mark.asyncio
async def test_deepseek_nonstream_request_keeps_usage_and_text(monkeypatch):
    module, model = _adapter("deepseek")
    usage = {"prompt_tokens": 100, "completion_tokens": 10}
    class Response:
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"choices": [{"message": {"content": "complete"}}], "usage": usage}).encode()
    recorded = []
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(model, "_record_usage_safe", recorded.append)
    text, tools = await model._complete_non_stream([], [])
    assert text == "complete" and tools == [] and recorded == [usage]
