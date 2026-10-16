"""A prior failure is a receipt, not a permanent ban on a new preparation."""
from copy import deepcopy

import pytest

from tests.wsc.test_semantic_production import isolated


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic_mode', [True, False])
@pytest.mark.parametrize('token_limit', [None, 100, 'usd'])
async def test_new_query_can_retry_retained_source_after_request_change(isolated, monkeypatch, semantic_mode, token_limit):
    from engine.query_loop import query_loop
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from memory.working import WorkingSnapshot, hydrate
    from memory import wsc_head_store
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from session.compression_source import compression_messages
    from prompt.assembler import PromptAssembler
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', '1' if semantic_mode else '0')
    store = MessageStore([Message(role='user', content='Generate report; publishing is prohibited.')])
    for _ in range(30):
        store.append(Message(role='assistant', content='prior observation ' + 'x' * 1500))
    store.append(assistant_text_message('', [ToolUse('unread', 'Read', {'file_path': 'result.txt'})]))
    store.append(tool_result_message('unread', 'Read', 'UNREAD_EXACT_RESULT',
                                    execution={'status': 'ok', 'complete': True}))
    original = deepcopy(store.items)
    registry = ToolRegistry(cwd=str(isolated))
    if not semantic_mode:
        registry.register(TodoWriteTool(cwd=str(isolated)))
    class Heavy:
        name = 'Heavy'
        size = 410000
        @staticmethod
        def is_read_only(): return True
        @staticmethod
        def is_concurrency_safe(): return True
        def schema(self):
            return {'name': self.name, 'description': 'x' * self.size, 'input_schema': {'type': 'object'}}
    heavy = Heavy()
    registry.register(heavy)
    working = WorkingSnapshot(session_id='resume')
    path, known, calls = isolated/'source.jsonl', set(), []
    def persist():
        record_transcript_sync(store.items, session_id='resume', path=path, known_ids=known)
    persist()
    original_bytes, original_rows = path.read_bytes(), deepcopy(compression_messages(store, working))
    class Summary:
        last_usage = None
        async def stream(self, messages, tools, abort):
            calls.append('summary')
            self.last_usage = {'prompt_tokens': 100, 'completion_tokens': 20,
                               'usd': 0.02, 'cost_cny': 0.14}
            # Only semantic mode returns a successful candidate on resumption.
            # D still fails; one new attempt must then continue with intact history.
            if semantic_mode and calls.count('summary') == 2:
                yield ModelChunk(kind='text_delta', text='Report pending. Publishing prohibited.')
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return Summary()
        async def stream(self, messages, tools, abort):
            calls.append('main')
            assert 'UNREAD_EXACT_RESULT' in str(messages)
            self.last_usage = {'prompt_tokens': 200, 'completion_tokens': 10}
            yield ModelChunk(kind='text_delta', text='continued')
    async def run(max_tokens=None):
        budget = BudgetTracker(max_turns=4, max_tokens=None if max_tokens == 'usd' else max_tokens,
                               usd_limit=0.02 if max_tokens == 'usd' else None)
        events = [event async for event in query_loop(store=store, model=Model(), tools=registry,
            prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(), budget=budget,
            working=working, persist_handoff=persist)]
        return events, budget
    first, first_budget = await run()
    assert calls == ['summary'] and first_budget.used_tokens == 120
    assert any(str(getattr(event, 'reason', '')).startswith('context_capacity_exceeded:') for event in first)
    assert working.compact_cursor == 0 and compression_messages(store, working) == original_rows
    assert not wsc_head_store.path_for('resume').exists()
    # This is a fresh, caller-initiated preparation, not an HTTP retry. Its full
    # request changes, while the historical source fingerprint stays identical.
    working = hydrate('resume')
    heavy.size = 315000
    registry.register(heavy)
    second, second_budget = await run(token_limit)
    assert calls == ['summary', 'summary'] + (['main'] if token_limit is None else [])
    assert second_budget.used_tokens == (330 if token_limit is None else 120)
    assert (working.compact_cursor > 0) is (semantic_mode and token_limit is None)
    assert store.items[:len(original)] == original
    assert path.read_bytes().startswith(original_bytes)
    assert not any(str(getattr(event, 'reason', '')).startswith('context_capacity_exceeded:') for event in second)
    if token_limit is not None:
        reason = 'budget_usd' if token_limit == 'usd' else 'budget'
        assert any(getattr(event, 'reason', '') == reason for event in second)
