"""Read-only exact transcript sources for the isolated handoff request."""
NAME = "HandoffSource"
MAX_CHARACTERS = 4096


def schema():
    return {"name": NAME, "description": "Returns an exact character range (offset) or bounded passages around literal matches (query) from one source message. Passage offsets and source length are returned. Total returned text is at most limit characters. No filesystem or task actions.",
        "input_schema": {"type": "object", "properties": {
            "message_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
            "query": {"type": "string", "minLength": 1, "maxLength": 256},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_CHARACTERS}},
            "required": ["message_id", "limit"], "oneOf": [{"required": ["offset"]}, {"required": ["query"]}], "additionalProperties": False}}


def read(arguments, sources):
    if not isinstance(arguments, dict) or set(arguments) not in ({"message_id", "offset", "limit"}, {"message_id", "query", "limit"}):
        raise ValueError("handoff_source_invalid_arguments")
    identity, limit = arguments["message_id"], arguments["limit"]
    offset, query = arguments.get("offset"), arguments.get("query")
    if (not isinstance(identity, str) or type(limit) is not int or not 1 <= limit <= MAX_CHARACTERS
            or ("offset" in arguments and (type(offset) is not int or offset < 0))
            or ("query" in arguments and (not isinstance(query, str) or not 1 <= len(query) <= min(256, limit)))):
        raise ValueError("handoff_source_invalid_arguments")
    matches = [row for row in sources if str(row.get("message_id") or row.get("id")) == identity]
    if len(matches) != 1:
        raise ValueError("handoff_source_not_unique")
    row = matches[0]
    from memory.wsc_handoff_source_content import render
    text = render(row)
    if query is not None:
        from memory.wsc_handoff_search import passages
        return {"message_id": identity, "role": row.get("role"), "query": query,
                "total_characters": len(text), **passages(text, query, limit)}
    end = min(len(text), offset + limit)
    return {"message_id": identity, "role": row.get("role"), "offset": offset,
            "total_characters": len(text), "content": text[offset:end],
            "text_complete": offset == 0 and end == len(text),
            "next_offset": end if end < len(text) else None}
