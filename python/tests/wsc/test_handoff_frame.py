from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate
from model.chunks import ModelChunk
from model.deepseek import _normalize_messages_for_openai
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_fact_disposition import prepared
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


def old_generate():
    # The old tool-only behavior is the single A/B variable; no dependence on
    # an ignored local experiment directory in CI or fresh checkouts.
    class ToolOnlyFrame:
        def observe(self, chunk): pass
        def message(self, uses):
            return {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': u.id,
                    'name': u.name, 'input': u.input} for u in uses]}
    async def baseline(*args, **kwargs):
        with patch('memory.wsc_handoff_frame.HandoffFrame', ToolOnlyFrame):
            return await generate(*args, **kwargs)
    return baseline


class Model:
    context_limit = 100000
    last_usage = None

    def __init__(self, *, rejection=False, signed=False, interrupted=False, tighten=False):
        self.requests, self.counted, self.limits = [], [], []
        self.rejection, self.signed, self.interrupted, self.tighten = rejection, signed, interrupted, tighten

    def for_handoff(self, *, max_tokens):
        self.limits.append(max_tokens)
        return self

    def context_input(self, messages, tools):
        self.counted.append(deepcopy(messages))
        return {'messages': messages, 'tools': tools}

    def context_token_measure(self, value):
        self.last_count = len(json.dumps(value, ensure_ascii=False))
        return self.last_count, 'test_wire_char_count'

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy(messages))
        self.last_usage = {'prompt_tokens': 13, 'completion_tokens': 17}
        if len(self.requests) == 1:
            if self.tighten:
                self.context_limit = self.last_count + self.limits[-1] + 1000
            yield ModelChunk(kind='text_delta', text='original body 中文')
            thought = 'R' * 17000 if self.tighten else 'original thought\n中文 '
            yield ModelChunk(kind='reasoning_delta', text=thought)
            if self.signed:
                yield ModelChunk(kind='reasoning_block', block={'type': 'thinking', 'text': thought, 'signature': 'fixture-signature'})
            yield ModelChunk(kind='tool_use', tool_use=ToolUse('first', 'TodoWrite' if self.rejection else 'HandoffSource',
                {'_raw': '{malformed'} if self.rejection else {'message_id': 'permit', 'offset': 0, 'limit': 64}))
            if self.interrupted:
                raise ValueError('fixture_interrupted')
        else:
            _, raw = prepared()
            yield ModelChunk(kind='tool_use', tool_use=ToolUse('valid', 'TodoWrite', raw))


async def run(function, model):
    sources, _ = prepared()
    before, usage = deepcopy(sources), []
    result = await function(model, [{'role': 'user', 'content': 'fixture'}], sources,
        TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert sources == before
    return result, usage


@pytest.mark.asyncio
@pytest.mark.parametrize('rejection', [False, True])
@pytest.mark.parametrize('signed', [False, True])
async def test_mainline_replays_original_frame_and_counts_it(rejection, signed):
    old = Model(rejection=rejection, signed=signed)
    await run(old_generate(), old)
    old_assistant = next(r for r in old.requests[1] if r['role'] == 'assistant')
    old_wire = _normalize_messages_for_openai([old_assistant])[0]
    assert 'reasoning_content' not in old_wire and old_wire['content'] == ''
    current = Model(rejection=rejection, signed=signed)
    result, usage = await run(generate, current)
    assert result.id == 'valid' and usage == [current.last_usage] * 2
    assistant = next(r for r in current.requests[1] if r['role'] == 'assistant')
    wire = _normalize_messages_for_openai([assistant])[0]
    assert wire['content'] == 'original body 中文'
    if not signed:
        assert wire['reasoning_content'] == 'original thought\n中文 '
    assert wire['tool_calls'] == old_wire['tool_calls']
    assert any(assistant in rows for rows in current.counted)
    if signed:
        assert [b for b in assistant['content'] if b['type'] == 'thinking'] == [
            {'type': 'thinking', 'text': 'original thought\n中文 ', 'signature': 'fixture-signature'}]
        assert not [b for b in assistant['content'] if b['type'] == 'reasoning']
        from model.anthropic import _blocks_to_anthropic
        native = _blocks_to_anthropic(assistant['content'])
        assert native[0] == {'type': 'thinking', 'thinking': 'original thought\n中文 ', 'signature': 'fixture-signature'}


@pytest.mark.asyncio
async def test_complete_frame_is_counted_before_next_request_admission():
    old = Model(tighten=True)
    result, _ = await run(old_generate(), old)
    assert result.id == 'valid' and len(old.requests) == 2
    current = Model(tighten=True)
    with pytest.raises(ValueError, match='handoff_request_exceeds_capacity'):
        await run(generate, current)
    assert len(current.requests) == 1


@pytest.mark.asyncio
async def test_interrupted_frame_does_not_make_a_second_request_and_usage_survives():
    model, usage = Model(interrupted=True), []
    sources, _ = prepared()
    with pytest.raises(ValueError, match='fixture_interrupted'):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], sources,
            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert len(model.requests) == 1 and usage == [model.last_usage]


def test_signed_replay_identity_is_validated():
    from memory.wsc_handoff_frame import HandoffFrame
    from engine.model_events import ModelProtocolError
    with pytest.raises(ModelProtocolError):
        HandoffFrame().observe(ModelChunk(kind='reasoning_block', block={'type': 'thinking', 'text': 'x', 'signature': ''}))
