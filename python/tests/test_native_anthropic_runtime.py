"""Native SSE facts survive actual tool execution, persistence and failure."""
import asyncio
import io
import json
from urllib.error import URLError
import pytest
import model.anthropic as adapter
from engine.abort import AbortController
from engine.query_engine import QueryEngine
from engine.model_events import ModelProtocolError, normalize_model_event
from model.chunks import ModelChunk
from msgtypes.events import FinalEvent, StoppedEvent, UsageEvent, ToolResultEvent
from msgtypes.message import assistant_text_message
from session.hydrate import load_session_messages
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from usage.pricing import split_usage


def lines(events):
    return ['data: ' + json.dumps(e) for e in events]


def usage_start():
    return {'type': 'message_start', 'message': {'usage': {'input_tokens': 20, 'output_tokens': 0,
        'cache_read_input_tokens': 80, 'cache_creation_input_tokens': 5}}}


def finish(reason='end_turn'):
    return [{'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 10}},
        {'type': 'message_stop'}]


def thought(index, text, signature):
    return [{'type': 'content_block_start', 'index': index, 'content_block': {'type': 'thinking'}},
        {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'thinking_delta', 'thinking': text}},
        {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'signature_delta', 'signature': signature}},
        {'type': 'content_block_stop', 'index': index}]


class Response:
    status_code = 200
    headers = {}
    def __init__(self, events, error=None): self.events, self.error = events, error
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def aiter_lines(self):
        for line in lines(self.events): yield line
        if self.error: raise self.error


@pytest.fixture
def offline(tmp_path, monkeypatch):
    for key in ('HOME', 'SESSIONS_DIR', 'MEMORY_DIR', 'USAGE_DIR', 'SNAPSHOTS_DIR', 'JOURNAL_DIR'):
        monkeypatch.setenv('XEYO_' + key, str(tmp_path / key.lower()))
    monkeypatch.setattr('usage.pricing.get_model_pricing', lambda *a, **k: {'input_hit': 0.2, 'input_miss': 2.0, 'output': 8.0})
    return tmp_path


def install(monkeypatch, responses):
    bodies = []
    class Client:
        def stream(self, *a, **kw):
            bodies.append(kw['json'])
            return responses[len(bodies) - 1]
    monkeypatch.setattr(adapter, 'get_shared_httpx_client', lambda timeout: Client())
    return bodies


def engine(path, model):
    registry = ToolRegistry()
    registry.register(EchoTool())
    return QueryEngine({'cwd': str(path), 'session_id': 'native-runtime', 'model_client': model,
        'tools': registry, 'provider': 'anthropic', 'model': 'offline-probe'})


@pytest.mark.asyncio
async def test_native_blocks_replay_after_tool_round_and_disk_restore(offline, monkeypatch):
    first = [usage_start(), *thought(0, 'first-thought', 'SIG-1'),
        {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'redacted_thinking', 'data': 'OPAQUE'}},
        *thought(2, 'second-thought', 'SIG-2'),
        {'type': 'content_block_start', 'index': 3, 'content_block': {'type': 'tool_use', 'id': 'echo-id', 'name': 'echo', 'input': {'text': 'fact'}}},
        {'type': 'content_block_stop', 'index': 3}, *finish('tool_use')]
    second = [usage_start(), {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'done'}}, *finish()]
    bodies = install(monkeypatch, [Response(first), Response(second)])
    model = adapter.AnthropicModelClient(api_key='offline', model='offline-probe', thinking='adaptive')
    records = []
    monkeypatch.setattr(model, '_record_usage_safe', records.append)
    runtime = engine(offline, model)
    events = [e async for e in runtime.submit('Read facts.')]
    assert sum(isinstance(e, ToolResultEvent) for e in events) == 1
    assert sum(isinstance(e, FinalEvent) for e in events) == 1
    wire = next(m for m in bodies[1]['messages'] if m['role'] == 'assistant')['content']
    assert wire[:3] == [{'type': 'thinking', 'thinking': 'first-thought', 'signature': 'SIG-1'},
        {'type': 'redacted_thinking', 'data': 'OPAQUE'}, {'type': 'thinking', 'thinking': 'second-thought', 'signature': 'SIG-2'}]
    assert 'reasoning' not in [b['type'] for b in wire]
    restored = load_session_messages(runtime.session_id)
    body = model._build_body([{'role': m.role, 'content': m.content} for m in restored], [], stream=True)
    replayed = next(m for m in body['messages'] if m['role'] == 'assistant')['content']
    assert replayed[:3] == wire[:3]
    assert runtime._session.budget.used_tokens == 230
    assert model.last_context_tokens == 105
    assert split_usage(model.last_usage) == (80, 25, 10)
    assert len(records) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['eof', 'max_tokens', 'refusal'])
async def test_native_incomplete_stream_is_not_a_final_and_usage_is_settled(offline, monkeypatch, ending):
    content = [usage_start(), {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'partial'}}]
    if ending != 'eof': content += finish(ending)
    install(monkeypatch, [Response(content)])
    model = adapter.AnthropicModelClient(api_key='offline', model='offline-probe')
    records = []
    monkeypatch.setattr(model, '_record_usage_safe', records.append)
    runtime = engine(offline, model)
    events = []
    with pytest.raises(ModelProtocolError):
        async for event in runtime.submit('facts'): events.append(event)
    assert not any(isinstance(e, FinalEvent) for e in events)
    assert len(records) == 1
    assert sum(isinstance(e, UsageEvent) for e in events) == 1
    assert runtime._session.budget.used_tokens == (105 if ending == 'eof' else 115)
    assert runtime.mutable_messages[-1].interrupted
    assert 'partial' in str(runtime.mutable_messages[-1].content)


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['reason', 'stop', 'both'])
async def test_native_accepts_either_completion_fact(offline, monkeypatch, ending):
    content = [usage_start(), {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'done'}}]
    content += finish() if ending == 'both' else finish()[:1] if ending == 'reason' else finish()[1:]
    install(monkeypatch, [Response(content)])
    model = adapter.AnthropicModelClient(api_key='offline', model='offline-probe')
    monkeypatch.setattr(model, '_record_usage_safe', lambda u: None)
    assert [chunk.text async for chunk in model.stream([], [], AbortController())] == ['done']


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['normal', 'eof', 'network'])
async def test_stdlib_usage_is_normalized_and_failure_safe(offline, monkeypatch, ending):
    events = [usage_start(), {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'partial'}}]
    if ending == 'normal': events += finish()
    class NativeResponse(io.BytesIO):
        status = 200
        headers = {}
        def readline(self, *args):
            line = super().readline(*args)
            if not line and ending == 'network': raise URLError('offline failure')
            return line
    monkeypatch.setattr(adapter, 'urlopen', lambda *a, **kw: NativeResponse(('\n'.join(lines(events)) + '\n').encode()))
    model = adapter.AnthropicModelClient(api_key='offline', model='offline-probe')
    records = []
    monkeypatch.setattr(model, '_record_usage_safe', records.append)
    caught = None
    try:
        _ = [c async for c in model._stream_stdlib([], [], AbortController())]
    except Exception as exc: caught = exc
    assert (caught is None) == (ending == 'normal')
    assert split_usage(model.last_usage) == (80, 25, 10 if ending == 'normal' else 0)
    assert len(records) == 1


def test_completed_native_block_does_not_erase_unfinished_thought():
    message = assistant_text_message('', reasoning='completepartial', reasoning_blocks=[
        {'type': 'thinking', 'text': 'complete', 'signature': 'SIG'}], interrupted=True)
    assert message.content[-1] == {'type': 'reasoning', 'text': 'partial'}


def test_native_thoughts_restore_in_ui_without_duplication_or_signature_exposure():
    from collections import deque
    from server.routers.sessions import _side_row_to_ui

    blocks = [{'type': 'thinking', 'text': 'first', 'signature': 'SIG-1'},
        {'type': 'redacted_thinking', 'data': 'OPAQUE'},
        {'type': 'thinking', 'text': 'second', 'signature': 'SIG-2'},
        {'type': 'text', 'text': 'result'}]
    row = {'role': 'assistant', 'content': blocks, 'id': 'native-ui', 'ts': 1}
    restored = _side_row_to_ui(row, 0, deque())
    assert [m['text'] for m in restored] == ['firstsecond', 'result']
    assert 'SIG' not in json.dumps(restored) and 'OPAQUE' not in json.dumps(restored)
    assert blocks[0]['signature'] == 'SIG-1'
    assert [m['text'] for m in _side_row_to_ui(row, 0, deque(), persisted_thoughts={'firstsecond'})] == ['result']


@pytest.mark.parametrize('block', [{'type': 'thinking', 'text': 'x'}, {'type': 'thinking', 'text': 1, 'signature': 'S'},
    {'type': 'text', 'text': 'x'}, {'type': 'redacted_thinking', 'data': ''}])
def test_replay_block_identity_is_validated(block):
    with pytest.raises(ModelProtocolError): normalize_model_event(ModelChunk(kind='reasoning_block', block=block))
