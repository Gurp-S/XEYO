from copy import deepcopy
import json

import pytest


def source_rows():
    def use(uid, name):
        return {'id': uid + '-source', 'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': uid, 'name': name, 'input': {'record': uid}}]}
    def result(uid, text):
        return {'type': 'tool_result', 'tool_use_id': uid, 'content': text, 'is_error': uid == 'a'}
    return [
        {'id': 'task', 'role': 'user', 'content': 'Current task: report the results.'},
        use('a', 'Read'), use('b', 'Read'),
        {'id': 'b-arrival', 'role': 'user', 'content': [result('b', 'normal receipt b=211')]},
        use('c', 'Bash'),
        {'id': 'mixed-arrival', 'role': 'user', 'content': [
            result('a', 'late error a=137'), result('c', 'normal receipt c=74'),
            {'type': 'text', 'text': 'Arrival note from the original user message.'}]},
    ]


def test_mixed_receipts_preserve_prior_complete_frame_and_both_provider_bodies(monkeypatch):
    from session.late_result_projection import ENV, project, supported
    from session.hydrate import messages_from_rows
    from session.late_result_guard import request_conflict
    from model.deepseek import DeepSeekModelClient
    from model.anthropic import AnthropicModelClient
    monkeypatch.setenv(ENV, '1')
    source = source_rows()
    original = deepcopy(source)
    prior = project(source[:4])
    projected = project(source)
    assert supported(messages_from_rows(source))
    assert projected[:4] == prior and source == original
    assert projected[2:4] == source[2:4]  # normal frame stays native and byte-for-byte unchanged
    assert request_conflict(projected) is None
    assert projected[4] == source[4]  # The current native invocation stays unchanged.
    assert projected[-1]['content'][0] == source[-1]['content'][1]
    assert projected[-1]['content'][-1] == source[-1]['content'][-1]
    meta = json.loads(projected[-1]['content'][1]['text'].split('\n')[0].removeprefix('Recorded tool result: '))
    assert meta == {'source_message_id': 'mixed-arrival', 'call_id': 'a', 'name': 'Read', 'arrival': 'non_adjacent', 'is_error': True}
    for client in [DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled'),
                   AnthropicModelClient(api_key='not-sent', model='claude-sonnet')]:
        body = client._build_body(projected, [], stream=False)
        wire = json.dumps(body, ensure_ascii=False)
        for text in ['late error a=137', 'normal receipt b=211', 'normal receipt c=74',
                     'Arrival note from the original user message.']:
            assert text in wire
    deepseek = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    before = deepseek._build_body(prior, [], stream=False)['messages']
    after = deepseek._build_body(projected, [], stream=False)['messages']
    assert after[:len(before)] == before
    assert [row['tool_call_id'] for row in after if row['role'] == 'tool'] == ['b', 'c']


@pytest.mark.asyncio
async def test_mixed_receipt_disk_restore_and_actual_main_loop(monkeypatch, tmp_path):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from prompt.assembler import PromptAssembler
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync, load_transcript
    from session.late_result_guard import request_conflict
    from tools.tool_registry import ToolRegistry
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    monkeypatch.setenv('XEYO_LATE_RESULT_PROJECTION', '1')
    store = MessageStore(messages_from_rows(source_rows()))
    path = tmp_path / 'mixed.jsonl'
    record_transcript_sync(store.items, session_id='mixed', path=path, known_ids=set())
    disk = path.read_bytes()
    store = MessageStore(messages_from_rows(load_transcript(path)))
    original = deepcopy(store.items)
    class Model:
        context_limit = 1000000
        last_usage = {}
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            assert request_conflict(messages) is None
            for text in ['late error a=137', 'normal receipt b=211', 'normal receipt c=74']:
                assert text in json.dumps(messages)
            yield ModelChunk(kind='text_delta', text='received')
    model = Model()
    events = [event async for event in query_loop(store=store, model=model, tools=ToolRegistry(cwd=str(tmp_path)),
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(),
        budget=BudgetTracker(max_turns=2), working=WorkingSnapshot(session_id='mixed'))]
    assert model.calls == 1, [getattr(event, 'reason', '') for event in events]
    assert store.items[:len(original)] == original and path.read_bytes() == disk
