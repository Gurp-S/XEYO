"""Read-only exact transcript sources for the isolated handoff request."""
import json

NAME = "HandoffSource"
MAX_CHARACTERS = 4096


def schema():
    return {"name": NAME, "description": "Returns an exact character range from one source message in this handoff transcript. No filesystem or task actions.",
        "input_schema": {"type": "object", "properties": {
            "message_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_CHARACTERS}},
            "required": ["message_id", "offset", "limit"], "additionalProperties": False}}


def read(arguments, sources):
    if not isinstance(arguments, dict) or set(arguments) != {"message_id", "offset", "limit"}:
        raise ValueError("handoff_source_invalid_arguments")
    identity, offset, limit = (arguments[key] for key in ("message_id", "offset", "limit"))
    if (not isinstance(identity, str) or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= MAX_CHARACTERS):
        raise ValueError("handoff_source_invalid_arguments")
    matches = [row for row in sources if str(row.get("message_id") or row.get("id")) == identity]
    if len(matches) != 1:
        raise ValueError("handoff_source_not_unique")
    row = matches[0]
    from synaptic.task_fact_sources import source_text
    text = source_text(row)
    if text is None:
        text = json.dumps(row.get("content"), ensure_ascii=False, separators=(",", ":"))
    end = min(len(text), offset + limit)
    return {"message_id": identity, "role": row.get("role"), "offset": offset,
            "total_characters": len(text), "content": text[offset:end],
            "next_offset": end if end < len(text) else None}
