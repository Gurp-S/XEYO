"""Validate a model-declared handoff before committing or folding anything.

Validation proves structure and source identity, not semantic truth or task
completion. The existing TodoWrite receipt remains the state authority.
"""
import json


def validate(raw, messages):
    from tools.todo_write_tool.todo_write_tool import parse_input, TodoWriteInput
    from synaptic.textutil import tool_use_blocks, tool_result_blocks
    if not isinstance(raw, dict) or set(raw) - {"todos", "checkpoint", "merge"}:
        raise ValueError("handoff_invalid_fields")
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 48_000:
        raise ValueError("handoff_too_large")
    if raw.get("merge", False) is not False or "checkpoint" not in raw:
        raise ValueError("handoff_full_state_required")
    parsed = parse_input(raw)
    if not isinstance(parsed, TodoWriteInput):
        raise ValueError("handoff_invalid_state")
    from memory.wsc_handoff_facts import validate_facts
    validate_facts(raw, messages)
    ids = [item.get("id") for item in raw["todos"]]
    if any(not isinstance(uid, str) or not uid.strip() for uid in ids) or len(set(ids)) != len(ids):
        raise ValueError("handoff_step_identity_invalid")
    checkpoint = parsed.checkpoint
    if any(item.status != "completed" for item in parsed.todos):
        if not checkpoint["objective"].strip() or not checkpoint["context_message_ids"]:
            raise ValueError("handoff_active_context_required")
    contexts, calls, results = {}, {}, {}
    for index, message in enumerate(messages):
        identity = message.get("id") or message.get("message_id")
        if identity:
            contexts.setdefault(str(identity), []).append(index)
        for use in tool_use_blocks(message):
            uid = use.get("id")
            if isinstance(uid, (str, int)) and uid:
                calls.setdefault(str(uid), []).append(index)
        for result in tool_result_blocks(message):
            uid = result.get("tool_use_id")
            if isinstance(uid, (str, int)) and uid:
                results.setdefault(str(uid), []).append((index, result))
    for identity in checkpoint["context_message_ids"]:
        if len(contexts.get(identity, ())) != 1:
            raise ValueError("handoff_context_source_not_unique")
    for identity in checkpoint["verification_call_ids"]:
        uses, receipts = calls.get(identity, ()), results.get(identity, ())
        if len(uses) != 1 or len(receipts) != 1 or uses[0] >= receipts[0][0]:
            raise ValueError("handoff_verification_source_not_unique")
        execution = receipts[0][1].get("execution")
        if isinstance(execution, dict) and (execution.get("complete") is False or execution.get("status") == "cancelled"):
            raise ValueError("handoff_verification_incomplete")
    return parsed
