"""Neutral rejection receipts in an isolated generation transcript only."""
import json


def invalid_arguments(raw):
    """Describe a provider's preserved malformed argument string, never repair it."""
    if not isinstance(raw, dict) or set(raw) != {'_raw'} or not isinstance(raw['_raw'], str):
        return None
    try:
        json.loads(raw['_raw'])
    except json.JSONDecodeError as exc:
        return {'error': 'handoff_invalid_json', 'message': exc.msg,
                'line': exc.lineno, 'column': exc.colno, 'position': exc.pos}
    return None


def rejected_frame(uses, facts, *, assistant=None):
    payload = json.dumps(facts, ensure_ascii=False)
    return [assistant if assistant is not None else
            {"role": "assistant", "content": [{"type": "tool_use", "id": use.id,
             "name": use.name, "input": use.input} for use in uses]},
            *[{"role": "tool", "tool_call_id": use.id, "name": use.name,
               "content": [{"type": "tool_result", "tool_use_id": use.id,
                            "content": payload, "is_error": True}]} for use in uses]]
