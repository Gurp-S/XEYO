"""Real declaration/Read/projection wiring and legacy actor compatibility."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from engine.abort import AbortController
from evals.wsc_production_continuation import ProductionTask, PublishedRead
from evals.wsc_native_actor_result import execute, legacy_message
from evals.wsc_task_actor_candidate import new_state, run, restore
from evals.wsc_task_actor_contracts import Calls, CLIENT, response
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_unfolded_source_ab import environment
from memory import wsc_projection
from msgtypes.message import ToolUse
from tests.wsc.test_task_phase import sources, declaration, DURABLE
from tools.base_tool import ToolResult


@pytest.fixture
def isolated(tmp_path):
    with environment(tmp_path):
        os.environ['XEYO_WSC'] = '1'
        wsc_projection._STATE.clear()
        yield tmp_path


async def declared_task(root, padding=True):
    rows = sources()
    if padding:
        rows += [{'id': f'past-{i}', 'role': 'assistant', 'content': 'Historical observation ' + str(i)}
                 for i in range(20)]
    task = ProductionTask(root, rows)
    original = deepcopy(task.source())
    async def declare(captured):
        assert captured == original
        return ToolUse('native-state', 'TodoWrite', declaration())
    receipt = await task.commit(declare)
    assert receipt['mechanical_status'] == 'VALIDATED' and receipt['semantic_status'] == 'SEMANTIC_UNVERIFIED'
    return task


@pytest.mark.asyncio
async def test_actual_commit_fold_projection_read_and_restart_are_one_input(isolated):
    task = await declared_task(isolated)
    before = deepcopy(task.source())
    prefix = task.path.read_bytes()
    result = task.fold()
    assert result['retired_region_end'] > 0 and result['compact_cursor'] > 0
    assert task.source() == before and task.path.read_bytes() == prefix
    assert DURABLE in result['hot'][0]['content']
    reader = PublishedRead(task, result['head'])
    cold_path = next(iter(result['head']['publication']['objects']))
    value = await reader.execute(ToolUse('read-archive', 'Read', {'file_path': cold_path, 'offset': 1, 'limit': 1000}), AbortController())
    assert not value.is_error and DURABLE in value.content
    restored = task.restart()
    assert restored.source() == task.source() and restored.project() == result['hot']
    assert restored.path.read_bytes() == prefix
    # Building a real provider body does not inject source metadata as content.
    model = ProviderFrameModel(Calls([]), CLIENT, 'prepare')
    body = model.body(result['hot'], reader.schemas())
    assert body == CLIENT._build_body(result['hot'], reader.schemas(), stream=False) | {'max_tokens': 4096, 'temperature': 0}


def test_source_message_ids_and_note_metadata_survive_native_conversion(isolated):
    rows = [{'message_id': 'source-id', 'role': 'user', 'content': 'text'},
            {'id': 'notice', 'role': 'system', 'content': 'machine fact',
             'note_key': 'state', 'note_kind': 'state', 'note_fp': 'version'}]
    before = deepcopy(rows)
    task = ProductionTask(isolated, rows)
    assert [item.id for item in task.store.items] == ['source-id', 'notice']
    assert task.store.items[1].note_key == 'state' and task.store.items[1].note_fp == 'version'
    assert rows == before
    with pytest.raises(ValueError, match='evaluation_source_identity_conflict'):
        ProductionTask(isolated / 'bad', [{'id': 'one', 'message_id': 'other', 'role': 'user', 'content': 'text'}])


def test_transcript_ui_rows_do_not_displace_native_tool_results(isolated):
    from session.hydrate import message_from_row
    from session.message_store import MessageStore

    rows = [
        {'id': 'request', 'role': 'user', 'content': 'Inspect the file.'},
        {'id': 'call', 'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'read-1', 'name': 'Read', 'input': {'file_path': 'file'}}]},
        {'id': 'ui', 'role': 'ui_thought', 'content': 'UI-only reasoning'},
        {'id': 'result', 'role': 'tool', 'tool_call_id': 'read-1', 'name': 'Read', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'read-1', 'content': 'exact result', 'is_error': False}]},
        {'id': 'answer', 'role': 'assistant', 'content': 'Observed.', 'narration': 'background',
         'interrupted': True},
        {'id': 'note', 'role': 'system', 'content': 'current fact', 'note_key': 'state',
         'note_kind': 'state', 'note_fp': 'v2', 'note_retracted': True},
    ]
    before = deepcopy(rows)
    production = MessageStore([m for r in rows if (m := message_from_row(deepcopy(r))) is not None])
    task = ProductionTask(isolated, rows)
    assert task.store.as_api_messages() == production.as_api_messages()
    assert [m.id for m in task.store.items] == [m.id for m in production.items]
    assert any(r['role'] == 'tool' for r in task.store.as_api_messages())
    task.persist()
    restored = task.restart()
    assert restored.source() == task.source()
    answer = next(m for m in restored.store.items if m.id == 'answer')
    assert answer.interrupted and answer.narration == 'background'
    note = next(m for m in restored.store.items if m.id == 'note')
    assert note.note_key == 'state' and note.note_fp == 'v2' and note.note_retracted
    assert rows == before


def test_legacy_receipt_adapter_cannot_promote_ui_content_to_tool(isolated):
    receipt = [{'type': 'tool_result', 'tool_use_id': 'old-call', 'content': 'exact\nreceipt',
                'is_error': True, 'execution': {'complete': False}}]
    rows = [{'role': 'assistant', 'id': 'call', 'content': [
        {'type': 'tool_use', 'id': 'old-call', 'name': 'Read', 'input': {}}]},
        {'role': 'ui_thought', 'id': 'ui', 'content': deepcopy(receipt)},
        {'role': 'user', 'message_id': 'receipt', 'content': deepcopy(receipt)}]
    task = ProductionTask(isolated, rows)
    assert [m.id for m in task.store.items] == ['call', 'receipt']
    result = task.store.items[-1]
    assert result.role == 'tool' and result.tool_call_id == 'old-call' and result.content == receipt


@pytest.mark.asyncio
async def test_invalid_declaration_does_not_publish_or_mutate_task(isolated):
    task = ProductionTask(isolated, sources())
    before = deepcopy(task.source())
    async def invalid(captured):
        raw = declaration()
        raw['checkpoint']['objective'] = ''
        return ToolUse('bad-state', 'TodoWrite', raw)
    with pytest.raises(ValueError, match='handoff_active_context_required'):
        await task.commit(invalid)
    assert task.source() == before
    assert 'bad-state' not in task.path.read_text(encoding='utf-8')


@pytest.mark.asyncio
async def test_too_short_history_cannot_be_reported_as_successful_fold(isolated):
    task = ProductionTask(isolated, [{'id': 'brief', 'role': 'user', 'content': 'brief'}])
    with pytest.raises(ValueError, match='evaluation_fold_not_published'):
        task.fold()


@pytest.mark.asyncio
async def test_real_read_errors_and_private_oracle_boundary_are_preserved(isolated):
    task = await declared_task(isolated)
    result = task.fold()
    reader = PublishedRead(task, result['head'])
    secret = isolated / 'private-expectation.json'
    secret.write_text('HIDDEN_GOLD', encoding='utf-8')
    denied = await reader.execute(ToolUse('denied', 'Read', {'file_path': str(secret)}), AbortController())
    assert denied.is_error and denied.error_kind == 'PERMISSION_DENIED' and 'HIDDEN_GOLD' not in denied.content
    cold_path = next(iter(reader.allowed))
    bad = await reader.execute(ToolUse('bad-arg', 'Read', {'file_path': str(cold_path), 'offset': 'not-an-integer'}), AbortController())
    assert bad.is_error and bad.error_kind == 'INVALID_ARGUMENT'
    cold_path.write_bytes(b'CORRUPTED_ARCHIVE')
    broken = await reader.execute(ToolUse('changed', 'Read', {'file_path': str(cold_path)}), AbortController())
    assert broken.is_error and 'CORRUPTED_ARCHIVE' not in broken.content


@pytest.mark.asyncio
async def test_native_receipt_preserves_literal_content_error_and_media_in_actor_wire(isolated):
    text = 'line\t"literal"\n中文'
    import base64
    import io
    from PIL import Image
    encoded = io.BytesIO()
    Image.new('RGB', (1, 1), (20, 40, 60)).save(encoded, format='PNG')
    image = 'data:image/png;base64,' + base64.b64encode(encoded.getvalue()).decode('ascii')
    class Native:
        async def execute(self, use, abort):
            return ToolResult(text, is_error=True, images=[image], error_kind='INVALID_ARGUMENT')
    first = response([('native-read', 'unused', '')])
    first['choices'][0]['message']['tool_calls'][0]['function'] = {'name': 'Read', 'arguments': '{"file_path":"cold"}'}
    model = ProviderFrameModel(Calls([first, response()]), CLIENT, 'native-actor')
    state = new_state([{'role': 'user', 'content': 'read fixture'}])
    snapshots = []
    await run(model, state, [], ExactArtifactSink(isolated / 'artifacts'), Native(), additional_requests=2, checkpoint=snapshots.append)
    assert state['completed'] and state['activity'][0]['is_error']
    receipt = next(row for row in state['pending_messages'] if row['role'] == 'tool')
    assert receipt['content'][0]['content'] == text
    assert receipt['content'][0]['execution']['error_kind'] == 'INVALID_ARGUMENT'
    assert receipt['content'][1]['image_url']['url'] == image
    body = model.calls.requests[1]
    assert next(row for row in body['messages'] if row['role'] == 'tool')['content'] == text
    assert image in json.dumps(body, ensure_ascii=False)


@pytest.mark.asyncio
async def test_legacy_dictionary_receipt_keeps_exact_old_shape(isolated):
    class Legacy:
        def call(self, name, args): return {'text': 'quote"\nnewline', 'count': 3}
    use = ToolUse('legacy', 'SourceRead', {})
    value, error, frame = await execute(use, ExactArtifactSink(isolated / 'artifacts'), Legacy())
    assert value == {'text': 'quote"\nnewline', 'count': 3} and error is False
    assert frame == {'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'legacy',
        'content': json.dumps(value, ensure_ascii=False), 'is_error': False}]}


@pytest.mark.asyncio
async def test_cancelled_native_execution_stays_unknown_and_not_replayed(isolated):
    class Native:
        async def execute(self, use, abort): raise asyncio.CancelledError()
    first = response([('cancelled-read', 'unused', '')])
    first['choices'][0]['message']['tool_calls'][0]['function'] = {'name': 'Read', 'arguments': '{"file_path":"cold"}'}
    model = ProviderFrameModel(Calls([first]), CLIENT, 'cancelled')
    sink, snapshots = ExactArtifactSink(isolated / 'artifacts'), []
    state = new_state([{'role': 'user', 'content': 'read fixture'}])
    with pytest.raises(asyncio.CancelledError):
        await run(model, state, [], sink, Native(), additional_requests=2, checkpoint=snapshots.append)
    assert snapshots[-1]['phase'] == 'tool_outcome_unknown' and not snapshots[-1]['activity']
    with pytest.raises(ValueError, match='actor_tool_outcome_unknown'):
        restore(ProviderFrameModel(Calls([]), CLIENT, 'restart'), snapshots[-1], sink)


@pytest.mark.asyncio
async def test_existing_actor_failure_contracts_still_pass(tmp_path, monkeypatch):
    from evals import wsc_task_actor_contracts as old
    monkeypatch.setattr(old, 'ROOT', tmp_path / 'old-actor-contracts')
    await old.main()
    report = json.loads((old.ROOT / 'report.json').read_text(encoding='utf-8'))
    assert report['passed'] == report['total'] == 13 and report['api_calls'] == 0


@pytest.mark.asyncio
async def test_cold_consumer_uses_production_context_without_leaking_source(isolated, monkeypatch):
    from evals import wsc_recall_cold_quality as cold
    from prompt.system_prompt import IDENTITY
    from prompt.fence import FENCE_POLICY

    class Captured:
        def __init__(self):
            self.report, self.requests = {}, []

        def save(self):
            pass

        async def call(self, body, label):
            self.requests.append(deepcopy(body))
            return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}]}

    monkeypatch.setattr(cold.trial.t.p.e, 'ROOT', isolated)
    calls = Captured()
    await cold.consumer(calls, 'context-contract')
    body, = calls.requests
    system = body['messages'][0]['content']
    assert IDENTITY in system and FENCE_POLICY in system
    assert str((isolated/'context-contract').resolve()) in system
    assert {item['function']['name'] for item in body['tools']} == {'Read', 'Grep'}
    assert body['tool_choice'] == 'auto'
    wire = json.dumps(body, ensure_ascii=False)
    assert '证据定位目录' in wire and '原始审计配置' in wire
    assert 'acct-larch-64' not in wire and '92461' not in wire
    assert not calls.report['cold_consumer'][0]['correct']
