"""Commit a generated handoff through the real task tool before any fold.

The caller owns request generation, usage accounting and capacity admission.
This transaction owns source consistency and append-only state publication.
"""
from copy import deepcopy
import hashlib
import json


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def persist_session(session):
    from session.record_transcript import record_transcript_sync
    items = session.messages.items
    record_transcript_sync(items[session.transcript_persist_index:], session_id=session.session_id,
                          session_persistence_disabled=session.is_session_persistence_disabled(),
                          known_ids=session.transcript_known_ids)
    session.transcript_persist_index = len(items)


async def commit(*, source, generate, store, tools, abort, persist):
    from memory.wsc_handoff_validation import validate
    from msgtypes.message import assistant_text_message, tool_result_message
    from synaptic.textutil import tool_use_blocks
    from synaptic.todo_snapshot import latest_todo_snapshot
    captured = deepcopy(source())
    before = fingerprint(captured)
    if abort.aborted:
        raise ValueError("handoff_cancelled")
    use = await generate(captured)
    if abort.aborted:
        raise ValueError("handoff_cancelled")
    if fingerprint(source()) != before:
        raise ValueError("handoff_source_changed")
    if use is None or use.name != "TodoWrite" or not isinstance(use.id, str) or not use.id:
        raise ValueError("handoff_invalid_call")
    if any(block.get("id") == use.id for row in captured for block in tool_use_blocks(row)):
        raise ValueError("handoff_call_identity_conflict")
    parsed = validate(use.input, captured)
    if tools.get("TodoWrite") is None:
        raise ValueError("handoff_task_tool_unavailable")
    store.append(assistant_text_message("", [use]))
    persist()  # The actual invocation is durable before the state write.
    result = await tools.run(use, abort)
    store.append(tool_result_message(use.id, use.name, result.content, is_error=result.is_error,
                                     status=result.status, execution=result.execution_metadata()))
    persist()  # Acknowledgement durability precedes compaction eligibility.
    if abort.aborted or result.is_error or result.status != "ok":
        raise ValueError("handoff_commit_failed")
    snapshot = latest_todo_snapshot(source())
    if (not snapshot.observed or snapshot.checkpoint != parsed.checkpoint
            or list(snapshot.records) != [item.to_dict() for item in parsed.todos]):
        raise ValueError("handoff_receipt_mismatch")
    return {"call_id": use.id, "source_fingerprint": before,
            "committed_source": snapshot.source, "task_count": len(snapshot.records)}
