from copy import deepcopy

import pytest

from memory.wsc_handoff_progress import ProgressError
from memory.wsc_handoff_validation import validate
from tests.wsc.test_handoff_fact_disposition import prepared
from tests.wsc.test_task_continuity import receipt, task


def empty(raw):
    raw['todos'] = []
    raw['checkpoint'] = {'objective': '', 'context_message_ids': [],
        'decisions': [], 'constraints': [], 'verification_call_ids': []}
    return raw


def test_empty_handoff_cannot_erase_active_task_without_bound_fresh_event():
    rows, raw = prepared()
    before = deepcopy(rows)
    with pytest.raises(ProgressError) as error:
        validate(empty(raw), rows, require_phase=True)
    assert error.value.detail['changes'] == [
        {'id': 'report', 'from_status': 'in_progress', 'to_status': 'absent'}]
    assert rows == before


@pytest.mark.parametrize('event', ['old', 'missing', 'machine', 'duplicate'])
def test_omission_cannot_use_old_ambiguous_or_machine_source(event):
    rows, raw = prepared()
    empty(raw)
    raw['checkpoint']['context_message_ids'] = ['permit' if event == 'old' else event]
    if event == 'machine':
        rows.append({'id': event, 'role': 'user', 'content': 'state', 'note_key': 'state'})
    if event == 'duplicate':
        rows += [{'id': event, 'role': 'user', 'content': 'state'}] * 2
    with pytest.raises(ValueError):
        validate(raw, rows, require_phase=True)


def test_explicit_new_cancellation_can_clear_and_old_history_is_unchanged():
    rows, raw = prepared()
    rows[-1]['content'] = '取消当前任务。'
    before = deepcopy(rows)
    empty(raw)
    raw['checkpoint']['context_message_ids'] = ['next']
    validate(raw, rows, require_phase=True)
    assert rows == before


def test_partial_unfinished_omission_is_subject_to_same_progress_contract():
    rows, raw = prepared()
    prior = deepcopy(raw)
    prior['todos'].append(task('pending-step', 'pending'))
    rows += receipt('new-base', prior['todos'], prior['checkpoint'])
    rows[-1]['id'] = 'new-base-source'
    with pytest.raises(ProgressError) as error:
        validate(raw, rows, require_phase=True)
    assert error.value.detail['changes'] == [
        {'id': 'pending-step', 'from_status': 'pending', 'to_status': 'absent'}]


def test_removing_completed_steps_does_not_invent_new_progress_requirement():
    rows, raw = prepared()
    prior = deepcopy(raw)
    prior['todos'].append(task('done-step', 'completed'))
    rows += receipt('new-base', prior['todos'], prior['checkpoint'])
    rows[-1]['id'] = 'new-base-source'
    validate(raw, rows, require_phase=True)


@pytest.mark.asyncio
async def test_generation_rejects_empty_snapshot_then_accepts_unchanged_task():
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows, raw = prepared()
    before, requests = deepcopy(rows), []
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens):
            return self
        async def stream(self, messages, schemas, abort):
            candidate = empty(deepcopy(raw)) if not requests else deepcopy(raw)
            if requests:
                assert 'handoff_progress_source_missing' in str(messages[-1])
                assert 'absent' in str(messages[-1])
            requests.append(deepcopy(messages))
            yield ModelChunk(kind='tool_use', tool_use=ToolUse(f'declare-{len(requests)}', 'TodoWrite', candidate))
    result = await generate(Model(), [{'role': 'user', 'content': 'fixture'}], rows,
        TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    assert result.input['todos'] == raw['todos']
    assert result.input['checkpoint'] == raw['checkpoint']
    assert len(requests) == 2 and rows == before
