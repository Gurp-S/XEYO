"""A complete unread result crosses real pre-send capacity preparation."""
from copy import deepcopy

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('result_bytes', [260000, 420000])
@pytest.mark.parametrize('nonadjacent', [False, True])
async def test_unread_large_result_is_presented_whole_or_stops_before_any_model_send(monkeypatch, tmp_path, native, result_bytes, nonadjacent):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    monkeypatch.setenv('XEYO_SESSIONS_DIR', str(tmp_path / 'sessions'))
    monkeypatch.setenv('XEYO_SPILL_DIR', str(tmp_path / 'spill'))
    monkeypatch.setenv('XEYO_WSC', str(int(native)))
    monkeypatch.setenv('XEYO_LATE_RESULT_PROJECTION', str(int(nonadjacent)))
    monkeypatch.setattr('memory.wsc_projection._STATE', {})
    monkeypatch.setattr('engine.first_sniff.maybe_first_sniff_text', lambda **kwargs: '')
    store = MessageStore([Message(role='user', id='spec', content='当前任务：根据完整读回结果写报告')])
    for i in range(30):
        store.append(Message(role='assistant', content='旧工作记录 ' + 'x' * 2000))
    if not nonadjacent:
        for i in range(12):
            store.append(Message(role='assistant', content='当时结果尚未到达 ' + 'y' * 2000))
    invocation_index = len(store.items)
    store.append(assistant_text_message('', [ToolUse('late-read', 'Read', {'file_path': 'source.txt'})]))
    if nonadjacent:
        for i in range(12):
            store.append(Message(role='assistant', content='当时结果尚未到达 ' + 'y' * 2000))
    body = 'RESULT_BEGIN\n' + 'z' * result_bytes + '\nRESULT_END'
    store.append(tool_result_message('late-read', 'Read', body))
    original = deepcopy(store.items)
    path, known = tmp_path / 'transcript.jsonl', set()
    def persist():
        record_transcript_sync(store.items, session_id='unread-capacity', path=path, known_ids=known)
    persist()
    prefix = path.read_bytes()
    tools = ToolRegistry(cwd=str(tmp_path))
    tools.register(TodoWriteTool(cwd=str(tmp_path)))
    calls = []
    from synaptic.textutil import tool_result_blocks, tool_result_text
    def contains_complete_result(messages):
        return (any(body in tool_result_text(block) for row in messages for block in tool_result_blocks(row))
                or any(body in block.get('text', '') for row in messages if isinstance(row.get('content'), list)
                       for block in row['content'] if isinstance(block, dict) and block.get('type') == 'text'))
    class Handoff:
        last_usage = {}
        async def stream(self, messages, tools, abort):
            calls.append('handoff')
            assert contains_complete_result(messages)
            from tests.wsc._fixtures import declared_report_phase
            yield ModelChunk(kind='tool_use', tool_use=ToolUse('state', 'TodoWrite', {
                'todos': [{'id': 'report', 'content': '写报告', 'status': 'pending', 'activeForm': '写报告'}],
                'checkpoint': {'objective': '根据完整结果写报告', 'context_message_ids': ['spec'],
                               'phase_state': declared_report_phase('spec')}}))
    class Model:
        context_limit = 100000
        last_usage = {}
        def for_handoff(self, max_tokens): return Handoff()
        async def stream(self, messages, tools, abort):
            calls.append('main')
            assert contains_complete_result(messages)
            from model.deepseek import DeepSeekModelClient
            wire = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')._build_body(messages, tools, stream=False)
            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for item in value.values(): yield from strings(item)
                elif isinstance(value, list):
                    for item in value: yield from strings(item)
            assert any(body in text for text in strings(wire))
            yield ModelChunk(kind='text_delta', text='结果全文已接收')
    working = WorkingSnapshot(session_id='unread-capacity')
    events = [event async for event in query_loop(store=store, model=Model(), tools=tools,
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(),
        budget=BudgetTracker(max_turns=4), working=working, persist_handoff=persist)]
    assert store.items[:len(original)] == original and path.read_bytes().startswith(prefix)
    if result_bytes == 420000:
        assert calls == [] and working.compact_cursor == 0
        assert path.read_bytes() == prefix
        assert any(getattr(event, 'reason', '') == 'handoff_request_exceeds_capacity' for event in events)
    else:
        assert calls == ['handoff', 'main'], [getattr(event, 'reason', '') for event in events]
        assert working.compact_cursor <= invocation_index


@pytest.mark.asyncio
async def test_known_late_receipt_stops_before_pair_repair_can_erase_it(monkeypatch, tmp_path):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop, _repair_unpaired_tool_calls
    from memory.working import WorkingSnapshot
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.tool_registry import ToolRegistry
    monkeypatch.setenv('XEYO_HOME', str(tmp_path))
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    monkeypatch.setenv('XEYO_LATE_RESULT_PROJECTION', '0')
    store = MessageStore([Message(role='user', content='current task'),
        assistant_text_message('', [ToolUse('late', 'Read', {'file_path': 'spec'})]),
        Message(role='assistant', content='before arrival'), tool_result_message('late', 'Read', 'complete receipt')])
    original = deepcopy(store.items)
    _repair_unpaired_tool_calls(store)
    assert store.items == original
    class Model:
        calls = 0
        async def stream(self, *args, **kwargs):
            self.calls += 1
            yield
    model = Model()
    working = WorkingSnapshot(session_id='known-late')
    events = [event async for event in query_loop(store=store, model=model, tools=ToolRegistry(),
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(),
        budget=BudgetTracker(max_turns=2), working=working)]
    assert store.items == original and model.calls == 0 and working.compact_cursor == 0
    assert any(getattr(event, 'reason', '') == 'tool_result_sequence_conflict: call_ids=late' for event in events)
