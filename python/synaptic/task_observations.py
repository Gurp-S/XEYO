"""Phase-scoped exact execution quotes; never decision or instruction authority."""
import hashlib
import json
import os

ENV = 'XEYO_WSC_EXECUTION_OBSERVATIONS'


def enabled():
    return os.environ.get(ENV, '').strip().lower() in {'1', 'true', 'on', 'yes'}


def schema():
    return {'type': 'array', 'maxItems': 16, 'description':
        'Exact result quotes selected by the model, bound to declared verification calls and phases. Total encoded observation size is at most 8192 bytes.',
        'items': {'type': 'object', 'additionalProperties': False,
            'properties': {key: {'type': 'string', 'minLength': 1}
                           for key in ('call_id', 'phase_id', 'quote')},
            'required': ['call_id', 'phase_id', 'quote']}}


def normalize(records, checkpoint):
    if not isinstance(records, list) or len(records) > 16:
        raise ValueError('invalid_task_observations')
    phases = {p['id'] for p in checkpoint.get('phase_state', {}).get('phases', [])}
    seen = set()
    for item in records:
        if (not isinstance(item, dict) or set(item) != {'call_id', 'phase_id', 'quote'}
                or any(not isinstance(v, str) or not v.strip() for v in item.values())
                or item['phase_id'] not in phases
                or item['call_id'] not in checkpoint['verification_call_ids']):
            raise ValueError('invalid_task_observation_binding')
        key = (item['call_id'], item['phase_id'], item['quote'])
        if key in seen:
            raise ValueError('duplicate_task_observation')
        seen.add(key)
    if len(json.dumps(records, ensure_ascii=False).encode()) > 8192:
        raise ValueError('task_observations_too_large')
    return [dict(item) for item in records]


def resolve(messages, checkpoint, before):
    from synaptic.task_verification import collect
    from synaptic.textutil import tool_result_blocks
    records = checkpoint.get('observations', [])
    if not records:
        return [], [], ()
    receipts, _, _ = collect(messages, list(dict.fromkeys(item['call_id'] for item in records)), before, inline_bytes=0)
    by_call = {item['call_id']: item for item in receipts}
    facts, unknown, nodes = [], [], []
    current = checkpoint.get('phase_state', {}).get('current_phase_id')
    for item in records:
        receipt = by_call.get(item['call_id'])
        block = None if receipt is None else next(
            (b for b in tool_result_blocks(messages[receipt['source']]) if b.get('tool_use_id') == item['call_id']), None)
        execution = (block or {}).get('execution') or {}
        text = (block or {}).get('content')
        if isinstance(text, list) and all(isinstance(p, dict) and p.get('type') == 'text' and isinstance(p.get('text'), str) for p in text):
            text = '\n'.join(p['text'] for p in text)
        if (not isinstance(text, str) or item['quote'] not in text
                or not isinstance(execution, dict) or execution.get('complete') is False
                or execution.get('status') == 'cancelled'):
            unknown.append({'call_id': item['call_id'], 'reason': 'observation_source_not_verified'})
            continue
        nodes.extend((receipt['input_source'], receipt['source']))
        if item['phase_id'] == current:
            facts.append({**item, 'source': receipt['source'], 'is_error': receipt['is_error'],
                'result_sha256': hashlib.sha256(text.encode()).hexdigest()})
    return facts, unknown, tuple(dict.fromkeys(nodes))


def validate_sources(raw, messages):
    checkpoint = raw['checkpoint']
    _, unknown, _ = resolve(messages, checkpoint, len(messages))
    if unknown:
        raise ValueError('handoff_observation_source_not_verified')
    from synaptic.todo_snapshot import latest_todo_snapshot
    prior = latest_todo_snapshot(messages)
    before = prior.checkpoint or {}
    current = checkpoint.get('phase_state', {}).get('current_phase_id')
    if (prior.active_count and current is not None
            and current == before.get('phase_state', {}).get('current_phase_id')
            and any(item.get('status') != 'completed' for item in raw.get('todos', []))):
        after = checkpoint.get('observations', [])
        if any(item['phase_id'] == current and item not in after for item in before.get('observations', [])):
            raise ValueError('handoff_current_phase_observation_omitted')
