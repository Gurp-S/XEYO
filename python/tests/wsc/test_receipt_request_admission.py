from copy import deepcopy

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
async def test_archived_late_receipt_does_not_block_valid_restored_request(monkeypatch, tmp_path, native):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory.runtime import force_compact
    from memory import wsc_projection
    from model.chunks import ModelChunk
    from prompt.assembler import PromptAssembler
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    from session.record_transcript import record_transcript_sync, load_transcript
    from session.late_result_guard import displaced_calls, request_conflict
    from tests.wsc.test_task_continuity import receipt, task
    from tools.tool_registry import ToolRegistry
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    monkeypatch.setenv('XEYO_WSC', str(int(native)))
    monkeypatch.setenv('XEYO_LATE_RESULT_PROJECTION', '0')
    source = [
        {'id': 'plan', 'role': 'user', 'content': 'Current task: report the recorded receipt.'},
        {'id': 'invoke', 'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'late', 'name': 'Read', 'input': {'file_path': 'spec'}}]},
        {'id': 'interim', 'role': 'assistant', 'content': 'Receipt pending.'},
        {'id': 'arrival', 'role': 'tool', 'tool_call_id': 'late', 'content': [{'type': 'tool_result', 'tool_use_id': 'late', 'content': 'full real receipt=137'}]},
    ]
    source.extend(receipt('checkpoint', [task('report', 'in_progress', 'report receipt')],
                          {'objective': 'report receipt', 'context_message_ids': ['plan'], 'verification_call_ids': ['late']}))
    for index in range(24):
        source.append({'id': f'work-{index}', 'role': 'assistant', 'content': 'recorded observation ' + 'field ' * 500})
    store = MessageStore(messages_from_rows(source))
    assert displaced_calls(store.items) == ['late']
    path = tmp_path / 'source.jsonl'
    record_transcript_sync(store.items, session_id='admission', path=path, known_ids=set())
    disk = path.read_bytes()
    working = WorkingSnapshot(session_id='admission-' + str(native))
    rows = compression_messages(store, working)
    wsc_projection._STATE.clear()
    emitted = force_compact(rows, working, cwd=tmp_path)
    assert working.compact_cursor > 4 and request_conflict(emitted) is None
    frozen = deepcopy(emitted[0])
    flush(working.session_id, working)
    working = hydrate(working.session_id)
    wsc_projection._STATE.clear()
    store = MessageStore(messages_from_rows(load_transcript(path)))
    original = deepcopy(store.items)
    class Model:
        context_limit = 1000000
        last_usage = {}
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            assert request_conflict(messages) is None
            assert any(row == frozen for row in messages)
            yield ModelChunk(kind='text_delta', text='continued')
    model = Model()
    events = [event async for event in query_loop(store=store, model=model, tools=ToolRegistry(cwd=str(tmp_path)),
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(),
        budget=BudgetTracker(max_turns=2), working=working)]
    assert model.calls == 1, [getattr(event, 'reason', '') for event in events]
    assert store.items[:len(original)] == original and path.read_bytes() == disk
