"""Structural coverage after a committed state; no task-switch inference."""
from synaptic.textutil import message_blocks, tool_use_blocks


def needs_refresh(messages, snapshot):
    if not snapshot.observed or snapshot.checkpoint is None:
        return True
    calls = {}
    for row in messages:
        for use in tool_use_blocks(row):
            if isinstance(use.get("id"), str):
                calls.setdefault(use["id"], []).append(use.get("name"))
    compact_ids = {uid for uid, names in calls.items() if names == ["Compact"]}
    for row in messages[snapshot.source + 1:]:
        if row.get("note_key"):
            continue
        blocks = message_blocks(row)
        if blocks and all((block.get("type") == "tool_use" and block.get("name") == "Compact")
            or (block.get("type") == "tool_result" and block.get("tool_use_id") in compact_ids) for block in blocks):
            continue
        return True
    return False
