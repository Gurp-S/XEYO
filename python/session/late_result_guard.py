"""Identify retained receipts that adjacency cleanup would discard."""
from collections import Counter

from session.tool_sequence import _tool_use_ids
from session.result_identity import result_ids


def call_counts(messages):
    return Counter(str(block['id']) for message in messages if message.role == 'assistant' and isinstance(message.content, list)
                   for block in message.content if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('id'))


def displaced_calls(messages):
    """A sequence boundary is observable before a later receipt arrives."""
    counts = call_counts(messages)
    from session.recovery_result_chain import supersessions
    supplements = supersessions(messages)
    pending, displaced = set(), set()
    for index, message in enumerate(messages):
        if message.role == 'assistant':
            displaced.update(pending)
            pending = _tool_use_ids(message)
        elif [uid for uid in result_ids(message) if (index, uid) not in supplements]:
            pending.difference_update(uid for uid in result_ids(message) if (index, uid) not in supplements)
        elif not message.hidden:
            displaced.update(pending)
            pending.clear()
    receipts = Counter(uid for index, message in enumerate(messages) for uid in result_ids(message)
                       if uid and (index, uid) not in supplements)
    displaced.update(uid for uid, count in counts.items() if count > 1)
    displaced.update(uid for uid, count in receipts.items() if uid not in counts or count > 1)
    displaced.update('source:' + message.id for message in messages if '' in result_ids(message))
    return sorted(displaced)


def conflicts(messages):
    calls = call_counts(messages)
    results = Counter(uid for message in messages for uid in result_ids(message) if uid)
    pending, seen, late = set(), set(), []
    for message in messages:
        if message.role == 'assistant':
            pending = _tool_use_ids(message)
            seen.update(pending)
        elif result_ids(message):
            for uid in result_ids(message):
                if uid in pending:
                    pending.remove(uid)
                elif uid in seen and calls[uid] == 1 and results[uid] == 1:
                    late.append(uid)
        elif not message.hidden:
            pending.clear()
    return late


def request_conflict(rows):
    """Admission follows the actual request view, never the archival store."""
    from msgtypes.message import Message
    from session.late_result_projection import enabled, supported
    items = [Message(role=row['role'], content=row.get('content', ''),
                     id=row.get('message_id') or row.get('id') or '',
                     tool_call_id=row.get('tool_call_id'), note_key=row.get('note_key', '')) for row in rows]
    ids = displaced_calls(items)
    from session.recovery_result_chain import supersessions
    ids = sorted(set(ids) | {uid for _index, uid in supersessions(items)})
    if ids and (not enabled() or not supported(items)):
        return 'tool_result_sequence_conflict: call_ids=' + ','.join(ids)
    return None
