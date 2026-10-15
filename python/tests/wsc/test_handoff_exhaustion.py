from copy import deepcopy
from contextlib import nullcontext
from unittest.mock import patch

import pytest

from engine.abort import AbortController
from engine.model_events import ModelProtocolError
from memory.wsc_handoff_exhaustion import next_limit
from memory.wsc_handoff_generation import generate
from model.chunks import ModelChunk
from model.output_exhaustion import OutputLimitError
from model.stream_end import validate_stream_end
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_fact_disposition import prepared
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


@pytest.mark.parametrize('reason', ['length', 'max_tokens'])
def test_provider_end_fact_has_specific_compatible_type(reason):
    with pytest.raises(OutputLimitError) as caught:
        validate_stream_end({'finish_reason': reason, 'has_output': True})
    assert isinstance(caught.value, ModelProtocolError)
    assert caught.value.finish_reason == reason
    assert str(caught.value) == 'model stream ended with finish_reason=' + reason
    assert next_limit(caught.value, 2048) == 4096


@pytest.mark.parametrize('reason', ['content_filter', 'refusal', None])
def test_other_end_failures_are_not_output_recovery(reason):
    with pytest.raises(ModelProtocolError) as caught:
        validate_stream_end({'finish_reason': reason, 'has_output': True})
    assert not isinstance(caught.value, OutputLimitError)
    assert next_limit(caught.value, 2048) is None


def test_existing_explicit_output_recovery_opt_out_remains_effective(monkeypatch):
    from memory.wsc_handoff_output_retry import ENV
    monkeypatch.delenv(ENV, raising=False)
    assert next_limit(OutputLimitError('length'), 2048) == 4096
    monkeypatch.setenv(ENV, '0')
    assert next_limit(OutputLimitError('length'), 2048) is None


class Model:
    context_limit = 100000
    last_usage = None

    def __init__(self, *, raw=None, error=None, always=False, small=False, cancelled=False, unknown_usage=False):
        self.raw = raw if raw is not None else prepared()[1]
        self.error = error if error is not None else OutputLimitError('length')
        self.always, self.small, self.cancelled, self.unknown_usage = always, small, cancelled, unknown_usage
        self.requests, self.caps = [], []

    def for_handoff(self, max_tokens):
        self.caps.append(max_tokens)
        self.output = max_tokens
        return self

    def context_input(self, messages, tools):
        return {'messages': messages, 'tools': tools}

    def context_token_measure(self, value):
        return 100, 'fixture_complete_request'

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy(messages))
        fail = self.always or len(self.requests) == 1
        self.last_usage = None if self.unknown_usage else {'prompt_tokens': 100, 'completion_tokens': self.output if fail else 12}
        if fail:
            if self.small:
                self.context_limit = 100 + self.output + 1
            if self.cancelled:
                abort.abort('fixture')
            yield ModelChunk(kind='reasoning_delta', text='incomplete thought')
            yield ModelChunk(kind='tool_use', tool_use=ToolUse('partial-never-committed', 'TodoWrite', self.raw))
            raise self.error
        yield ModelChunk(kind='tool_use', tool_use=ToolUse('complete', 'TodoWrite', self.raw))


async def invoke(model, *, admit_next=None):
    rows, _ = prepared()
    before, usage = deepcopy(rows), []
    result = await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
                            TodoWriteTool().schema(), AbortController(), account=usage.append,
                            admit_next=admit_next, scope_protocol=True)
    assert rows == before
    return result, usage


@pytest.mark.asyncio
async def test_same_valid_request_new_allowance_ab_and_original_usage_kept():
    old = Model()
    with patch('memory.wsc_handoff_exhaustion.next_limit', return_value=None):
        with pytest.raises(OutputLimitError):
            await invoke(old)
    assert len(old.requests) == 1
    model, admitted = Model(), []
    result, usage = await invoke(model, admit_next=lambda: admitted.append(True))
    from memory.wsc_handoff_output_budget import reservation
    initial = reservation(prepared()[0])
    assert result.id == 'complete' and model.caps == [initial, min(8192, initial * 2)]
    assert model.requests[0] == model.requests[1] and len(admitted) == 1
    assert 'partial-never-committed' not in str(model.requests[1])
    assert usage == [{'prompt_tokens': 100, 'completion_tokens': initial}, {'prompt_tokens': 100, 'completion_tokens': 12}]


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [OSError('network'), ModelProtocolError('model stream ended with finish_reason=length'),
                                 ModelProtocolError('refusal'), ValueError('invalid signature')])
async def test_no_transport_or_text_matched_or_protocol_failure_regeneration(error):
    model = Model(error=error)
    with pytest.raises(type(error)):
        await invoke(model)
    assert len(model.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', ['capacity', 'caller_budget', 'request_limit', 'output_limit', 'cancelled'])
async def test_all_existing_limits_still_bound_generation(limit):
    model = Model(small=limit == 'capacity', always=limit == 'output_limit', cancelled=limit == 'cancelled')
    def admit():
        if limit == 'caller_budget':
            raise ValueError('fixture_budget')
    ctx = patch('memory.wsc_handoff_generation.MAX_REQUESTS', 1) if limit == 'request_limit' else nullcontext()
    with ctx:
        with pytest.raises(ValueError):
            await invoke(model, admit_next=admit)
    assert len(model.requests) == (3 if limit == 'output_limit' else 1)
    assert max(model.caps) <= 8192


@pytest.mark.asyncio
async def test_unknown_usage_remains_unknown_and_caller_can_refuse_extra_request():
    rows, _ = prepared()
    model, usage = Model(unknown_usage=True), []
    def admit():
        assert usage == [None]
        raise ValueError('unknown_usage_budget')
    with pytest.raises(ValueError, match='unknown_usage_budget'):
        await generate(model, [], rows, TodoWriteTool().schema(), AbortController(), account=usage.append, admit_next=admit)
    assert len(model.requests) == 1 and usage == [None]


@pytest.mark.asyncio
async def test_actual_transaction_publishes_only_complete_declaration(tmp_path):
    from tests.wsc.test_handoff_transaction import setup
    from memory.wsc_handoff_transaction import commit
    from memory.working import WorkingSnapshot
    from session.compression_source import compression_messages
    from synaptic.textutil import tool_use_blocks
    store, registry, raw = setup(tmp_path)
    model, persisted = Model(raw=raw), []
    source = lambda: compression_messages(store, WorkingSnapshot())
    before = deepcopy(source())
    async def declaration(rows):
        return await generate(model, [], rows, TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    result = await commit(source=source, generate=declaration, store=store, tools=registry,
                          abort=AbortController(), persist=lambda: persisted.append(deepcopy(source())))
    assert result['call_id'] == 'complete' and source()[:len(before)] == before
    ids = [u['id'] for row in source() for u in tool_use_blocks(row)]
    assert ids == ['complete'] and len(persisted) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['deepseek', 'openai_compat', 'anthropic'])
@pytest.mark.parametrize('transport', ['httpx', 'stdlib'])
async def test_explicit_exhaustion_type_survives_real_provider_adapter(monkeypatch, name, transport):
    import json
    from tests.test_model_stream_termination import _adapter, _Response, _install
    module, model = _adapter(name)
    monkeypatch.setattr(model, '_record_usage_safe', lambda usage: None)
    if name == 'anthropic':
        reason = 'max_tokens'
        events = [('message_start', {'type': 'message_start', 'message': {'id': 'offline', 'role': 'assistant'}}),
                  ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
                  ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'incomplete'}}),
                  ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': reason}}),
                  ('message_stop', {'type': 'message_stop'})]
        lines = [line for event, value in events for line in ('event: ' + event, 'data: ' + json.dumps(value), '')]
    else:
        reason = 'length'
        lines = ['data: ' + json.dumps({'choices': [{'delta': {'content': 'incomplete'}}]}),
                 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': reason}]}), 'data: [DONE]']
    if transport == 'httpx':
        _install(monkeypatch, module, _Response(lines))
    else:
        class Response:
            status = 200
            headers = {}
            def __init__(self): self.lines = iter(lines)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def close(self): pass
            def readline(self):
                value = next(self.lines, None)
                return (value + '\n').encode('utf-8') if value is not None else b''
        monkeypatch.setattr(module, 'httpx', None)
        monkeypatch.setattr(module, 'urlopen', lambda *args, **kwargs: Response())
    with pytest.raises(OutputLimitError) as caught:
        _ = [c async for c in model.stream([], [], AbortController())]
    assert caught.value.finish_reason == reason
