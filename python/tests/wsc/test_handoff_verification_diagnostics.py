"""Rejected evidence identifies the failing binding without prescribing action."""
from copy import deepcopy
import pytest
from memory.wsc_handoff_validation import StateError, validate
from tests.wsc.test_handoff_fact_disposition import prepared


@pytest.mark.parametrize('failure,uses,results', [('missing', 0, 0), ('duplicate_use', 2, 1), ('duplicate_result', 1, 2)])
def test_nonunique_binding_has_exact_identity_and_observed_counts(failure, uses, results):
    rows, raw = prepared()
    uid = 'verify'
    if failure == 'missing':
        uid = 'historical-dangling-id'
        raw['checkpoint']['verification_call_ids'] = [uid]
    elif failure == 'duplicate_use':
        rows.append(deepcopy(rows[3]))
    else:
        rows.append(deepcopy(rows[4]))
    before = deepcopy(rows)
    with pytest.raises(StateError) as caught:
        validate(raw, rows, require_phase=True)
    detail = caught.value.detail
    assert detail['error'] == 'handoff_verification_source_not_unique'
    assert detail['verification_call_id'] == uid
    assert detail['invocation_count'] == uses
    assert detail['receipt_count'] == results
    assert len(detail['invocation_sources']) == uses
    assert len(detail['receipt_sources']) == results
    assert detail['field'] == '$.checkpoint.verification_call_ids'
    assert rows == before


@pytest.mark.asyncio
async def test_generation_reports_binding_facts_then_accepts_valid_declaration():
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows, raw = prepared()
    attempts = []
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            candidate = deepcopy(raw)
            if not attempts:
                candidate['checkpoint']['verification_call_ids'] = ['absent']
            else:
                import json
                detail = json.loads(messages[-1]['content'][0]['content'])
                assert detail['verification_call_id'] == 'absent'
                assert detail['invocation_count'] == detail['receipt_count'] == 0
            attempts.append(True)
            yield ModelChunk(kind='tool_use', tool_use=ToolUse(f'declare-{len(attempts)}', 'TodoWrite', candidate))
    result = await generate(Model(), [{'role': 'user', 'content': 'Task state observation.'}], rows,
                            TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    assert len(attempts) == 2 and result.input['checkpoint']['verification_call_ids'] == ['verify']
