from copy import deepcopy
import json

import pytest


def rows():
    return [{'id': 'objective', 'role': 'user', 'content': 'current report'},
            {'id': 'invocation', 'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'late', 'name': 'Read', 'input': {'file_path': 'spec'}}]},
            {'id': 'intervening', 'role': 'assistant', 'content': 'result not yet received'},
            {'id': 'arrival', 'role': 'tool', 'name': 'Read', 'tool_call_id': 'late',
             'content': [{'type': 'tool_result', 'tool_use_id': 'late', 'content': 'exact result\nvalue=137'}]}]


def test_hydration_and_api_source_preserve_arrival_order_and_ids(monkeypatch):
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from memory.working import WorkingSnapshot
    from session.compression_source import compression_messages
    source = rows()
    items = messages_from_rows(source)
    assert [item.id for item in items] == [row['id'] for row in source]
    store = MessageStore(items)
    original = deepcopy(store.items)
    api = store.as_api_messages()
    assert store.items == original and len(api) == len(source)
    canonical = compression_messages(store, WorkingSnapshot())
    assert canonical[-1]['role'] == 'tool' and canonical[-1]['message_id'] == 'arrival'
    assert canonical[-1]['content'] == source[-1]['content']


def test_default_wire_projection_has_full_result_without_moving_original_rows(monkeypatch):
    from session.late_result_projection import project, ENV
    from model.deepseek import DeepSeekModelClient
    source = rows()
    original = deepcopy(source)
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setenv(ENV, '0')
    assert project(source) is source
    monkeypatch.delenv(ENV, raising=False)
    projected = project(source)
    assert source == original and [row['id'] for row in projected] == [row['id'] for row in source]
    assert projected[-1]['role'] == 'user' and 'value=137' in projected[-1]['content'][0]['text']
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    body = client._build_body(projected, [], stream=False)
    wire = json.dumps(body, ensure_ascii=False)
    assert 'value=137' in wire and 'Recorded tool invocation' in wire
    assert not any(row.get('role') == 'tool' for row in body['messages'])
    from model.anthropic import AnthropicModelClient
    anthropic = AnthropicModelClient(api_key='not-sent', model='claude-sonnet')
    assert 'value=137' in json.dumps(anthropic._build_body(projected, [], stream=False), ensure_ascii=False)


@pytest.mark.asyncio
async def test_actual_main_loop_resumes_default_late_source_after_disk_hydration(monkeypatch, tmp_path):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from prompt.assembler import PromptAssembler
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync, load_transcript
    from tools.tool_registry import ToolRegistry
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    monkeypatch.delenv('XEYO_LATE_RESULT_PROJECTION', raising=False)
    store = MessageStore(messages_from_rows(rows()))
    path, known = tmp_path / 'transcript.jsonl', set()
    record_transcript_sync(store.items, session_id='late', path=path, known_ids=known)
    original = path.read_bytes()
    store = MessageStore(messages_from_rows(load_transcript(path)))
    prefix = deepcopy(store.items)
    class Model:
        context_limit = 1000000
        last_usage = {}
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            assert 'exact result\nvalue=137' in messages[4]['content'][0]['text']
            assert 'arrival' in messages[4]['content'][0]['text']
            yield ModelChunk(kind='text_delta', text='receipt observed')
    model = Model()
    events = [event async for event in query_loop(store=store, model=model, tools=ToolRegistry(cwd=str(tmp_path)),
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(),
        budget=BudgetTracker(max_turns=2), working=WorkingSnapshot(session_id='late'))]
    assert model.calls == 1 and store.items[:len(prefix)] == prefix and path.read_bytes() == original
    assert not any('tool_result_sequence_conflict' in getattr(event, 'reason', '') for event in events)


def test_nontext_late_payload_stays_in_source_and_is_not_claimed_supported(monkeypatch):
    from session.hydrate import messages_from_rows
    from session.late_result_projection import project, supported, ENV
    source = rows()
    source[-1]['content'][0]['content'] = [{'type': 'image', 'data': 'sample'}]
    monkeypatch.setenv(ENV, '1')
    items = messages_from_rows(source)
    assert len(items) == len(source) and not supported(items)
    assert project(source) is source


def test_other_missing_or_ambiguous_pairs_are_not_admitted_by_late_candidate(monkeypatch):
    from session.hydrate import message_from_row
    from session.late_result_projection import supported
    source = rows()
    source.append({'id': 'new-open-call', 'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 'missing', 'name': 'Read', 'input': {}}]})
    assert not supported([message_from_row(row) for row in source])
    source = rows()
    source.append(dict(source[-1], id='duplicate-result'))
    assert not supported([message_from_row(row) for row in source])


def test_pair_cut_closes_transitive_spans_across_intervening_messages():
    from memory.runtime import pair_safe_cut
    source = [ {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'a', 'name': 'Read', 'input': {}}]},
               {'role': 'assistant', 'content': 'interim'},
               {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'b', 'name': 'Read', 'input': {}}]},
               {'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'a', 'content': 'a'}]},
               {'role': 'assistant', 'content': 'interim'},
               {'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'b', 'content': 'b'}]} ]
    assert pair_safe_cut(source, 5) == 0
    assert pair_safe_cut(source, 6) == 6


def test_receipt_arrival_only_appends_to_prearrival_factual_request(monkeypatch):
    from session.late_result_projection import ENV, project
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from memory.working import WorkingSnapshot
    from session.compression_source import compression_messages
    monkeypatch.setenv(ENV, '1')
    original = rows()
    before = MessageStore(messages_from_rows(original[:-1]))
    prior = project(compression_messages(before, WorkingSnapshot()))
    assert len(before.items) == 3 and 'Recorded tool invocation' in prior[1]['content'][0]['text']
    after = MessageStore(messages_from_rows(original))
    current = project(compression_messages(after, WorkingSnapshot()))
    assert current[:len(prior)] == prior
    assert (current[-1].get('id') or current[-1].get('message_id')) == 'arrival'


def test_native_nested_receipt_identity_does_not_create_duplicate_unknown_result():
    from session.hydrate import messages_from_rows
    source = rows()
    result = dict(source[-1])
    result.pop('tool_call_id')
    items = messages_from_rows([source[1], result])
    assert len(items) == 2 and items[1].content == result['content']


def test_user_role_receipt_blocks_are_results_not_new_sequence_boundaries(monkeypatch):
    from session.hydrate import message_from_row, messages_from_rows
    from session.message_store import MessageStore
    from engine.query_loop import _repair_unpaired_tool_calls
    from session.late_result_guard import displaced_calls
    from session.late_result_projection import ENV, project
    source = rows()
    result = dict(source[-1], role='user')
    result.pop('tool_call_id')
    adjacent = [source[1], result]
    assert displaced_calls([message_from_row(row) for row in adjacent]) == []
    store = MessageStore(messages_from_rows(adjacent))
    assert len(store.items) == 2
    original = deepcopy(store.items)
    _repair_unpaired_tool_calls(store)
    assert store.items == original
    monkeypatch.setenv(ENV, '1')
    assert project(adjacent) is adjacent


def test_duplicate_identity_inside_one_frame_is_not_unique():
    from session.hydrate import message_from_row
    from session.late_result_projection import supported
    source = rows()
    source[1]['content'].append(deepcopy(source[1]['content'][0]))
    assert not supported([message_from_row(row) for row in source])


@pytest.mark.parametrize('uid', ['unknown', ''])
def test_unknown_or_missing_receipt_identity_is_preserved_and_not_supported(uid):
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.late_result_projection import supported
    source = [{'id': 'orphan-source', 'role': 'tool', 'content': [
        {'type': 'tool_result', 'tool_use_id': uid, 'content': 'retained actual result'}]}]
    items = messages_from_rows(source)
    assert len(items) == 1 and items[0].content == source[0]['content']
    store = MessageStore(items)
    assert len(store.as_api_messages()) == 1 and store.items == items
    assert not supported(items)


@pytest.mark.parametrize('adjacent', [True, False])
def test_one_receipt_message_resolves_all_call_blocks_without_synthetic_results(monkeypatch, adjacent):
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from engine.query_loop import _repair_unpaired_tool_calls
    from session.late_result_guard import displaced_calls
    from session.late_result_projection import ENV, project, supported
    source = rows()
    source[1]['content'].append({'type': 'tool_use', 'id': 'second', 'name': 'Read', 'input': {'file_path': 'other'}})
    source[-1].pop('tool_call_id')
    source[-1]['role'] = 'user'
    source[-1]['content'].append({'type': 'tool_result', 'tool_use_id': 'second', 'content': 'second exact result=211'})
    if adjacent:
        source.pop(2)
    items = messages_from_rows(source)
    assert len(items) == len(source) and supported(items)
    assert displaced_calls(items) == ([] if adjacent else ['late', 'second'])
    store = MessageStore(items)
    original = deepcopy(items)
    _repair_unpaired_tool_calls(store)
    assert store.items == original
    monkeypatch.setenv(ENV, '1')
    projected = project(source)
    if not adjacent:
        assert project(source[:-1]) == projected[:-1]
        from model.deepseek import DeepSeekModelClient
        wire = json.dumps(DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')._build_body(projected, [], stream=False))
        assert 'value=137' in wire and 'second exact result=211' in wire


@pytest.mark.parametrize('second_id', ['late', 'unknown', ''])
def test_bad_second_result_block_cannot_hide_behind_valid_first_block(second_id):
    from session.hydrate import messages_from_rows
    from session.late_result_projection import supported
    from session.late_result_guard import displaced_calls
    source = rows()
    source[-1].pop('tool_call_id')
    source[-1]['content'].append({'type': 'tool_result', 'tool_use_id': second_id, 'content': 'other receipt'})
    items = messages_from_rows(source)
    assert len(items) == len(source) and items[-1].content == source[-1]['content']
    assert displaced_calls(items) and not supported(items)


@pytest.mark.parametrize('mode', ['different-envelope', 'multiple-with-envelope', 'missing-second-with-envelope'])
def test_envelope_identity_cannot_override_or_fill_another_receipt(mode):
    from session.hydrate import messages_from_rows
    from session.late_result_guard import displaced_calls
    from session.late_result_projection import supported
    source = rows()
    if mode == 'different-envelope':
        source[-1]['tool_call_id'] = 'different'
    else:
        source[-1]['content'].append({'type': 'tool_result', 'tool_use_id': '' if mode.startswith('missing') else 'second', 'content': 'actual second'})
    items = messages_from_rows(source)
    assert [item.id for item in items] == [row['id'] for row in source]
    assert items[-1].content == source[-1]['content']
    assert 'source:arrival' in displaced_calls(items) and not supported(items)
