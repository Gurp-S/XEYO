"""Experimental compactor-only raw-user grounding; no applicability inference."""
from copy import deepcopy
import json


def add_context(messages, sources, *, max_bytes=16000):
    visible = {row.get('message_id') or row.get('id') for row in messages if row.get('role') in {'user', 'human'}}
    texts = [row.get('content') for row in messages if row.get('role') in {'user', 'human'}]
    selected = []
    def envelope(rows):
        return json.dumps({'historical_user_sources': rows}, ensure_ascii=False, separators=(',', ':'))
    for row in reversed(sources):
        if row.get('role') not in {'user', 'human'} or row.get('note_key'):
            continue
        uid = row.get('message_id') or row.get('id')
        if (uid is not None and uid in visible) or row.get('content') in texts:
            continue
        candidate = [deepcopy(row), *selected]
        if len(envelope(candidate).encode('utf-8')) > max_bytes:
            break  # Never cut a clause, or leap over a newer large user record.
        selected = candidate
    if not selected:
        return messages, {'records': 0, 'bytes': 0}
    content = envelope(selected)
    at = next((i for i, row in enumerate(messages) if row.get('role') != 'system'), len(messages))
    return [*messages[:at], {'role': 'user', 'content': content}, *messages[at:]], {
        'records': len(selected), 'bytes': len(content.encode('utf-8')),
        'message_ids': [row.get('message_id') or row.get('id') for row in selected]}
