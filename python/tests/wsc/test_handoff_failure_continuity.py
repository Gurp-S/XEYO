"""Rejected/cancelled isolated handoffs do not publish or retire task history."""
from copy import deepcopy

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('failure', ['omission', 'cancelled'])
async def test_failed_capacity_handoff_preserves_frozen_state_and_unread_result(monkeypatch, tmp_path, native, failure, semantic=False):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from prompt.assembler import PromptAssembler
    from session.compression_source import compression_messages
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from synaptic.todo_snapshot import latest_todo_snapshot
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from tests.wsc.test_handoff_fact_disposition import prepared
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_WSC', str(int(native)))
    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', str(int(semantic)))
    monkeypatch.setattr('memory.wsc_projection._STATE', {})
    monkeypatch.setattr('engine.first_sniff.maybe_first_sniff_text', lambda **kw: '')
    rows, _ = prepared()
    store = MessageStore(messages_from_rows(rows[:-1]))
    for i in range(45):
        store.append(Message(role='assistant', content=f'archive {i} ' + 'x' * 2000))
    working = WorkingSnapshot(session_id='failure-continuity')
    source = lambda: compression_messages(store, working)
    initial = force_compact(source(), working, cwd=tmp_path)
    assert working.compact_cursor > 0
    frozen = initial[0]['content']
    store.append(assistant_text_message('', [ToolUse('fresh-unread', 'Read', {'file_path': 'result.txt'})]))
    unread = 'UNCONSUMED_RESULT:' + 'z' * 12000
    store.append(tool_result_message('fresh-unread', 'Read', unread,
        execution={'complete': True, 'status': 'ok'}))
    baseline = deepcopy(source())
    old_state = latest_todo_snapshot(baseline)
    cursor = working.compact_cursor
    objects = {p: p.read_bytes() for p in tmp_path.rglob('*.txt')}
    path, known = tmp_path / 'transcript.jsonl', set()
    def persist():
        record_transcript_sync(store.items, session_id=working.session_id, path=path, known_ids=known)
    persist()
    prefix = path.read_bytes()
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    class Heavy:
        name = 'Heavy'
        @staticmethod
        def is_read_only(): return True
        @staticmethod
        def is_concurrency_safe(): return True
        def schema(self):
            return {'name': self.name, 'description': 'x' * 360000, 'input_schema': {'type': 'object'}}
    registry.register(Heavy())
    requests = []
    class Handoff:
        last_usage = None
        async def stream(self, messages, tools, abort):
            requests.append(True)
            if failure == 'cancelled':
                abort.abort('fixture_cancelled')
            yield ModelChunk(kind='tool_use', tool_use=ToolUse(f'rejected-{len(requests)}', 'TodoWrite', {
                'todos': [], 'checkpoint': {'objective': '', 'context_message_ids': [],
                    'verification_call_ids': [], 'decisions': [], 'constraints': []}}))
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return Handoff()
        async def stream(self, messages, tools, abort):
            raise AssertionError('Main model cannot run after failed capacity preparation')
            yield
    events = [event async for event in query_loop(store=store, model=Model(), tools=registry,
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(),
        budget=BudgetTracker(max_turns=10), working=working, persist_handoff=persist,
        include_memory_index=False)]
    expected = 'aborted' if failure == 'cancelled' else 'handoff_progress_source_missing'
    assert any(getattr(e, 'reason', '') == expected for e in events)
    assert requests and working.compact_cursor == cursor
    assert path.read_bytes() == prefix and source() == baseline
    after_state = latest_todo_snapshot(source())
    assert after_state.records == old_state.records and after_state.checkpoint == old_state.checkpoint
    after = project_for_model(source(), working, context_limit=100000, capacity_managed=True,
        cwd=tmp_path, include_memory_index=False)
    assert after[0]['content'].startswith(frozen) and unread in str(after)
    flush(working.session_id, working)
    restored = hydrate(working.session_id)
    monkeypatch.setattr('memory.wsc_projection._STATE', {})
    resumed = project_for_model(source(), restored, context_limit=100000, capacity_managed=True,
        cwd=tmp_path, include_memory_index=False)
    assert resumed[0]['content'].startswith(frozen) and unread in str(resumed)
    assert restored.compact_cursor == cursor
    assert all(p.read_bytes() == data for p, data in objects.items())


@pytest.mark.asyncio
async def test_cancelled_semantic_generation_keeps_frozen_state_and_unread_result(monkeypatch, tmp_path):
    await test_failed_capacity_handoff_preserves_frozen_state_and_unread_result(
        monkeypatch, tmp_path, native=True, failure='cancelled', semantic=True)
