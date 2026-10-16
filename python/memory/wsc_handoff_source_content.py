"""One source-content view for exact handoff search and character ranges."""
import json

from synaptic.task_fact_sources import source_text


def render(row):
    content = row.get('content')
    if row.get('tool_calls') or row.get('function_call'):
        # These protocol fields are outside content; a content-only view loses them.
        return json.dumps(row, ensure_ascii=False, separators=(',', ':'))
    text = source_text(row)
    if text is not None and (isinstance(content, str) or
            isinstance(content, list) and all(isinstance(part, dict) and
                set(part) <= {'type', 'text'} and part.get('type') == 'text' for part in content)):
        return text
    return json.dumps(content, ensure_ascii=False, separators=(',', ':'))
