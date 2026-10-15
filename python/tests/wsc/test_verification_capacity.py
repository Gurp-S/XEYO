"""Active-phase bindings can grow within the existing checkpoint byte budget."""
from copy import deepcopy

import pytest

from synaptic.task_checkpoint import validate, MAX_DECLARATION_BYTES
from memory.wsc_handoff_generation import source_schema
from tests.wsc.test_handoff_fact_disposition import prepared
from tests.wsc._fixtures import msg_asst_use, msg_tool
from tools.todo_write_tool.todo_write_tool import TodoWriteTool, parse_input


def test_seventeenth_binding_is_representable_in_both_tool_schemas_and_parser():
    rows, raw = prepared()
    ids = ['verify']
    for i in range(16):
        uid = f'additional-{i}'
        ids.append(uid)
        rows += [msg_asst_use(uid, 'Read', {'file_path': 'receipt.txt'}), msg_tool(uid, 'Read', 'receipt')]
    raw['checkpoint']['verification_call_ids'] = ids
    assert validate(raw['checkpoint'])['verification_call_ids'] == ids
    assert parse_input(raw).checkpoint['verification_call_ids'] == ids
    schema = TodoWriteTool().schema()
    properties = schema['input_schema']['properties']['checkpoint']['properties']
    assert 'maxItems' not in properties['verification_call_ids']
    assert properties['context_message_ids']['maxItems'] == 16
    constrained, _ = source_schema(schema, rows)
    assert constrained['input_schema']['properties']['checkpoint']['properties']['verification_call_ids']['maxItems'] >= 17
    from memory.wsc_handoff_validation import validate as full_validate
    full_validate(raw, rows, require_phase=True)


def test_verification_growth_still_has_the_existing_total_byte_limit():
    _rows, raw = prepared()
    raw['checkpoint']['verification_call_ids'] = ['x' * MAX_DECLARATION_BYTES]
    with pytest.raises(ValueError, match='task_checkpoint_too_large'):
        validate(raw['checkpoint'])


def test_other_checkpoint_lists_keep_their_existing_limits():
    _rows, raw = prepared()
    checkpoint = deepcopy(raw['checkpoint'])
    checkpoint['context_message_ids'] = [f'context-{i}' for i in range(17)]
    with pytest.raises(ValueError, match='invalid_task_checkpoint_context_message_ids'):
        validate(checkpoint)
