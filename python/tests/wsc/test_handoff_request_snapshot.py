"""Presentation follows the request snapshot, not callers' later list edits."""
from copy import deepcopy

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['append', 'remove', 'rewrite', 'role', 'none'])
async def test_counting_wait_does_not_rebind_presentation_to_external_messages(change):
    sources = [{'role': 'user', 'message_id': 'spec', 'content': 'EXACT_SOURCE_332'}]
    messages = [] if change == 'append' else deepcopy(sources)
    original = deepcopy(messages)
    sent, usages = [], []

    class Model:
        context_limit = 100000
        last_usage = None

        def for_handoff(self, max_tokens): return self

        def context_input(self, request, tools):
            return {'messages': request, 'tools': tools}

        async def predict_context_tokens(self, request, tools, abort):
            if change == 'append': messages.extend(deepcopy(sources))
            elif change == 'remove': messages.clear()
            elif change == 'rewrite': messages[0]['content'] = 'CHANGED_OUTSIDE_REQUEST'
            elif change == 'role': messages[0]['role'] = 'assistant'
            return 100

        async def stream(self, request, tools, abort):
            sent.append(deepcopy(request))
            self.last_usage = {'prompt_tokens': 100, 'completion_tokens': 10}
            yield ModelChunk(kind='tool_use', tool_use=ToolUse('declare', 'TodoWrite', {
                'todos': [], 'checkpoint': {'objective': '', 'context_message_ids': ['spec']}}))

    result = await generate(Model(), messages, sources, TodoWriteTool().schema(),
                            AbortController(), account=usages.append)
    assert len(sent) == len(usages) == 1
    assert sent[0][:len(original)] == original
    if change == 'append':
        assert not any(row.get('content') == sources[0]['content'] for row in sent[0])
    record = result.presentation['sources'][0]
    assert record['complete'] is bool(original)
    assert record['presented_ranges'] == ([[0, len(sources[0]['content'])]] if original else [])


@pytest.mark.asyncio
async def test_capacity_rejection_does_not_confirm_prepared_source(monkeypatch):
    from memory.wsc_handoff_coverage import Coverage
    confirmed, sent, usages = [], [], []
    monkeypatch.setattr(Coverage, 'full', lambda self, uid: confirmed.append(uid))
    sources = [{'role': 'user', 'message_id': 'spec', 'content': 'EXACT_SOURCE_332'}]

    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        def context_input(self, messages, tools): return {'messages': messages, 'tools': tools}
        async def predict_context_tokens(self, messages, tools, abort): return self.context_limit
        async def stream(self, messages, tools, abort):
            sent.append(messages)
            yield ModelChunk(kind='text_delta', text='not reached')

    with pytest.raises(ValueError, match='^handoff_request_exceeds_capacity$'):
        await generate(Model(), sources, sources, TodoWriteTool().schema(),
                       AbortController(), account=usages.append)
    assert confirmed == sent == usages == []
