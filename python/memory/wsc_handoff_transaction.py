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


async def commit(*, source, generate, store, tools, abort, persist, require_phase=False,
                 admit_write=None, publish_guard=None, session_id=""):
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
    parsed = validate(use.input, captured, require_phase=require_phase)
    from memory.wsc_handoff_coverage import PresentedHandoff, validated
    presentation = validated(use.presentation, captured) if isinstance(use, PresentedHandoff) else None
    if tools.get("TodoWrite") is None:
        raise ValueError("handoff_task_tool_unavailable")
    # Admit the actual write in the frame that produced this declaration.
    # Generation can span several frames, each resetting tool-call counters.
    # A refusal must precede both invocation publication and state mutation.
    if admit_write is not None:
        admit_write()
    store.append(assistant_text_message("", [use]))
    def publish(result, execution):
        if publish_guard is not None:
            publish_guard()
        # Durable provenance of the isolated declaration call. This call does
        # not acknowledge task-model consumption of preceding tool results.
        execution = dict(execution or {}, compaction_handoff=True)
        if presentation is not None and not result.is_error and result.status == "ok":
            execution = dict(execution or {}, handoff_source_presentation=presentation)
        store.append(tool_result_message(use.id, use.name, result.content, is_error=result.is_error,
                                         status=result.status, execution=execution))
        persist()  # Acknowledgement durability precedes compaction eligibility.

    from session.execution_receipt import lookup
    # A historical receipt with a reused call ID cannot certify this attempt.
    # Lookup is optional evidence; missing/incomplete evidence stays unknown.
    prior_receipt = None
    execution_started = False
    try:
        persist()  # The actual invocation is durable before the state write.
        prior_receipt = lookup(session_id, use.id) if session_id else None
        execution_started = True
        result = await tools.run(use, abort)
    except BaseException:
        # The registry can fail after the tool returned (e.g. a later hook or
        # cancellation). Reuse its existing durable receipt, never replay the
        # write or infer completion from the proposed input/call-start marker.
        from tools.base_tool import ToolResult
        row = lookup(session_id, use.id) if execution_started and session_id else None
        if (row and row != prior_receipt and row.get("name") == use.name and row.get("phase") == "returned"
                and row.get("complete") and isinstance(row.get("content"), str)):
            result = ToolResult(row["content"], is_error=bool(row.get("is_error")),
                                status=row.get("status"))
            execution = row.get("execution")
        else:
            result = ToolResult(
                "[TodoWrite] TOOL_OUTCOME_UNKNOWN — result unavailable." if execution_started
                else "[TodoWrite] TOOL_NOT_STARTED — invocation publication failed.",
                is_error=True, error_kind="TOOL_OUTCOME_UNKNOWN" if execution_started
                else "HANDOFF_NOT_STARTED")
            execution = dict(result.execution_metadata(), complete=False)
        publish(result, execution)
        raise
    publish(result, result.execution_metadata())
    if abort.aborted or result.is_error or result.status != "ok":
        raise ValueError("handoff_commit_failed")
    snapshot = latest_todo_snapshot(source())
    if (not snapshot.observed or snapshot.checkpoint != parsed.checkpoint
            or list(snapshot.records) != [item.to_dict() for item in parsed.todos]):
        raise ValueError("handoff_receipt_mismatch")
    return {"call_id": use.id, "source_fingerprint": before,
            "committed_source": snapshot.source, "task_count": len(snapshot.records)}
