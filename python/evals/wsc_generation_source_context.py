"""Experimental generation-only source restoration; no production switch."""
from copy import deepcopy

from memory.wsc_semantic_input import for_generation
from memory.wsc_semantic_generation import PROMPT
from memory.wsc_handoff_recall import schema as source_schema
from memory.wsc_handoff_catalog import schema as catalog_schema
from memory.wsc_counted_input import CountedInput
from memory.wsc_timing import request_measure
from session.late_result_projection import project
from session.late_result_guard import request_conflict


async def select(messages, working, source, *, model, abort, cwd, output_tokens=4096):
    body = for_generation(messages, working, source, cwd=cwd)
    if body is messages:
        return body, {'selected': False, 'reason': 'no_verified_owned_head'}
    index = next(i for i, row in enumerate(body) if row.get('role') != 'system')
    restored = [*deepcopy(body[:index]), *deepcopy(project(source)[:working.compact_cursor]),
                *deepcopy(body[index+1:])]
    request = [*restored, {'role': 'user', 'content': PROMPT + (
        f'\nSource snapshot: {len(source)} records; HandoffCatalog returns identities and literal-query matches; '
        'HandoffSource returns exact source ranges.')}]
    if request_conflict(request):
        return body, {'selected': False, 'reason': 'source_protocol_conflict'}
    counted = CountedInput(model, abort)
    schemas = [source_schema(), catalog_schema()]
    await counted.prime(request, schemas)
    measured = request_measure(request, schemas, context_limit=getattr(model, 'context_limit', None), model=counted)
    selected = bool(measured.capacity and measured.input_tokens + output_tokens <= measured.capacity)
    return (restored if selected else body), dict(selected=selected,
        reason='within_capacity' if selected else 'capacity_unknown_or_exceeded',
        input_tokens=measured.input_tokens, output_reserve=output_tokens,
        capacity=measured.capacity, basis=measured.basis)
