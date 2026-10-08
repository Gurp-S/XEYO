"""Resolve exact task facts through committed declarations, never tool prose."""
from synaptic.textutil import message_blocks


def source_text(message):
    if message.get("role") not in {"user", "human", "assistant"} or message.get("note_key") or message.get("note_kind"):
        return None
    parts = [block.get("text", "") for block in message_blocks(message) if block.get("type") == "text"]
    return "\n".join(part for part in parts if isinstance(part, str)) or None


def resolve(messages, identity, field, quote):
    """A declaration can inherit only a whole same-field fact from its predecessor.

    Every edge reduces the transcript boundary. No cycles, substring slot
    matches, failed writes, or superseded declarations establish authority.
    Returned indices identify the exact original text/committed receipts.
    """
    from synaptic.todo_snapshot import latest_todo_snapshot
    pending = [(len(messages), identity, ())]
    visited = set()
    while pending:
        boundary, identity, chain = pending.pop()
        if (boundary, identity) in visited:
            continue
        visited.add((boundary, identity))
        prefix = messages[:boundary]
        indices = [i for i, row in enumerate(prefix)
                   if str(row.get("message_id") or row.get("id")) == identity]
        if len(indices) != 1:
            continue
        index = indices[0]
        text = source_text(messages[index])
        if text is not None:
            if quote in text:
                return (*chain, index)
            continue
        snapshot = latest_todo_snapshot(prefix)
        if not snapshot.observed or not snapshot.active_count or snapshot.checkpoint is None or snapshot.checkpoint_source != index:
            continue
        for fact in snapshot.checkpoint[field]:
            if isinstance(fact, str) and fact == quote:
                return (*chain, index)
            if (isinstance(fact, dict) and fact.get("quote") == quote
                    and fact.get("source_message_id") in snapshot.checkpoint["context_message_ids"]):
                pending.append((index, fact["source_message_id"], (*chain, index)))
    return None
