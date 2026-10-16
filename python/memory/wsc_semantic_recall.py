"""Bounded read-only compactor loop over a caller-captured source snapshot."""
from copy import deepcopy
import json

from memory.wsc_handoff_catalog import Catalog, schema as catalog_schema
from memory.wsc_handoff_recall import read, schema as source_schema
from memory.wsc_handoff_frame import HandoffFrame
from memory.wsc_handoff_generation import MAX_REQUESTS, MAX_READ_CALLS, MAX_RECALL_BYTES, MAX_RESPONSE_BYTES


async def generate(client, messages, abort, *, prompt, sources, account, output_tokens,
                   context_limit=None, admit_next=None, admit_read=None, guard=None, alternative_messages=None):
    from memory.wsc_counted_input import CountedInput
    from memory.wsc_timing import request_measure
    from memory.wsc_stream_cleanup import close_and_account
    from synaptic.textutil import tool_use_blocks
    from session.late_result_guard import request_conflict
    catalog = Catalog(sources) if sources is not None else None
    tools = [source_schema(), catalog_schema()] if catalog is not None else []
    suffix = [{'role': 'user', 'content': prompt + (
        f'\nSource snapshot: {len(sources)} records; HandoffCatalog returns identities and literal-query matches; '
        'HandoffSource returns exact source ranges.' if catalog is not None else '')}]
    request = deepcopy(messages) + suffix
    counted = CountedInput(client, abort)
    alternative_selected = False
    if alternative_messages is not None and context_limit:
        alternative = deepcopy(alternative_messages) + suffix
        abort.raise_if_aborted()
        if guard: guard()
        if not request_conflict(alternative):
            await counted.prime(alternative, tools)
            if guard: guard()
            measured = request_measure(alternative, tools, context_limit=context_limit, model=counted)
            if measured.capacity and measured.input_tokens + output_tokens <= measured.capacity:
                request = alternative
                alternative_selected = True
    seen = {block.get('id') for row in request for block in tool_use_blocks(row)}
    read_calls = recalled_bytes = 0
    for attempt in range(MAX_REQUESTS if tools else 1):
        abort.raise_if_aborted()
        if guard: guard()
        conflict = request_conflict(request)
        if conflict: raise ValueError(conflict)
        await counted.prime(request, tools)
        if guard: guard()
        measured = request_measure(request, tools, context_limit=context_limit, model=counted)
        if measured.capacity and measured.input_tokens + output_tokens > measured.capacity:
            raise ValueError('semantic_generation_capacity_exceeded')
        if attempt and admit_next: admit_next()
        frame, uses, size = HandoffFrame(), [], 0
        client.last_usage = None
        stream = client.stream(request, tools, abort)
        try:
            async for chunk in stream:
                abort.raise_if_aborted()
                frame.observe(chunk)
                size += len((chunk.text or '').encode('utf-8'))
                if chunk.kind == 'tool_use' and chunk.tool_use:
                    uses.append(chunk.tool_use)
                    size += len(json.dumps(chunk.tool_use.input, ensure_ascii=False).encode('utf-8'))
                if size > MAX_RESPONSE_BYTES or len(uses) > MAX_READ_CALLS:
                    raise ValueError('semantic_generation_output_limit')
        except Exception as exc:
            if alternative_selected:
                from common.errors import classify_llm_failure
                if classify_llm_failure(exc).code == 'context_window_exceeded':
                    raise ValueError('semantic_generation_capacity_exceeded') from exc
            raise
        finally:
            await close_and_account(stream, client, account)
        abort.raise_if_aborted()
        if guard: guard()
        if not uses:
            text = ''.join(frame.text).strip()
            if not text: raise ValueError('semantic_generation_empty')
            return text
        if any(use.name not in {tool['name'] for tool in tools} for use in uses):
            raise ValueError('semantic_generation_unexpected_tool')
        ids = [use.id for use in uses]
        if any(not isinstance(uid, str) or not uid or uid in seen for uid in ids) or len(set(ids)) != len(ids):
            raise ValueError('semantic_generation_call_identity_conflict')
        seen.update(ids)
        if attempt == MAX_REQUESTS - 1 or read_calls + len(uses) > MAX_READ_CALLS:
            raise ValueError('semantic_generation_recall_limit')
        results = []
        for use in uses:
            if admit_read: admit_read()
            read_calls += 1
            error = False
            try:
                value = read(use.input, sources) if use.name == 'HandoffSource' else catalog.read(use.input)
            except ValueError as exc:
                if str(exc) not in {'handoff_source_invalid_arguments', 'handoff_source_not_unique',
                                    'handoff_catalog_invalid_arguments', 'handoff_catalog_record_too_large'}:
                    raise
                value, error = {'error': str(exc), 'tool': use.name}, True
            payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
            recalled_bytes += len(payload.encode('utf-8'))
            if recalled_bytes > MAX_RECALL_BYTES:
                raise ValueError('semantic_generation_recall_limit')
            results.append({'role': 'tool', 'tool_call_id': use.id, 'name': use.name,
                'content': [{'type': 'tool_result', 'tool_use_id': use.id, 'content': payload, 'is_error': error}]})
        request.extend([frame.message(uses), *results])
