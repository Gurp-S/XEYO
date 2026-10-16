"""Select a committed semantic body for generation without editing live history."""
from pathlib import Path


def for_generation(messages, working, source, *, cwd=None):
    from memory import wsc_head_store as heads
    from memory.wsc_committed_head import KEY

    ref = working.wsc_timing_state.get(KEY)
    if (not isinstance(ref, dict) or ref.get('cursor') != working.compact_cursor
            or not isinstance(ref.get('path'), str) or not ref['path']):
        return messages
    head = heads.load(working.session_id, cwd=str(Path(cwd or Path.cwd()).resolve()),
        cursor=working.compact_cursor, messages=source,
        source_layout=working.compression_source_layout, record_path=ref['path'])
    if head is None:
        return messages
    checkpoint = head.lifecycle.get('semantic_checkpoint')
    end = checkpoint.get('body_chars') if isinstance(checkpoint, dict) else None
    if (type(end) is not int or not 0 < end <= len(head.text)
            or (end < len(head.text) and head.text[end:end+2] != '\n\n')):
        return messages  # Legacy/unknown ownership stays intact; never parse prose.
    # Only the leading installed summary is engine-owned. An identical quote
    # later in the transcript is still user/model material, not presentation.
    index = next((i for i, row in enumerate(messages) if row.get('role') != 'system'), None)
    if index is None:
        return messages
    row = messages[index]
    if (row.get('role') != 'assistant' or row.get('name') != 'session_summary'
            or row.get('content') != head.text):
        return messages
    return [*messages[:index], {**row, 'content': head.text[:end]}, *messages[index+1:]]
