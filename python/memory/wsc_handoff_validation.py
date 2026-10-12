"""Validate a model-declared handoff before committing or folding anything.

Validation proves structure and source identity, not semantic truth or task
completion. The existing TodoWrite receipt remains the state authority.
"""
import json


class StateError(ValueError):
    def __init__(self, code, **facts):
        super().__init__(code)
        self.detail = {"error": code, **facts}


def validate(raw, messages, *, require_phase=False):
    from tools.todo_write_tool.todo_write_tool import parse_input, TodoWriteInput
    from synaptic.textutil import tool_use_blocks, tool_result_blocks
    if not isinstance(raw, dict):
        raise StateError("handoff_invalid_fields", input_type=type(raw).__name__)
    extra = set(raw) - {"todos", "checkpoint", "merge", "context_disposition", "fact_disposition"}
    if extra:
        raise StateError("handoff_invalid_fields", field="root", extra_fields=sorted(extra))
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 48_000:
        raise ValueError("handoff_too_large")
    if raw.get("merge", False) is not False or "checkpoint" not in raw:
        raise ValueError("handoff_full_state_required")
    parsed = parse_input(raw)
    if not isinstance(parsed, TodoWriteInput):
        details = {"state_error": parsed.get("message")} if isinstance(parsed, dict) else {}
        checkpoint = raw.get("checkpoint")
        if isinstance(checkpoint, dict):
            extras = set(checkpoint) - {"objective", "context_message_ids", "decisions", "constraints", "verification_call_ids", "phase_state", "observations"}
            if extras:
                details.update(field="checkpoint", extra_fields=sorted(extras))
        raise StateError("handoff_invalid_state", **details)
    from memory.wsc_handoff_facts import validate_facts
    validate_facts(raw, messages)
    ids = [item.get("id") for item in raw["todos"]]
    if any(not isinstance(uid, str) or not uid.strip() for uid in ids) or len(set(ids)) != len(ids):
        raise ValueError("handoff_step_identity_invalid")
    checkpoint = parsed.checkpoint
    from synaptic.task_observations import validate_sources
    validate_sources({**raw, "checkpoint": checkpoint}, messages)
    if any(item.status != "completed" for item in parsed.todos):
        if not checkpoint["objective"].strip() or not checkpoint["context_message_ids"]:
            raise ValueError("handoff_active_context_required")
    contexts, calls, results = {}, {}, {}
    from session.recovery_result_chain import supersessions
    replaced = {(prior, uid) for (_actual, uid), prior in supersessions(messages).items()}
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
                if (index, str(uid)) not in replaced:
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
    from memory.wsc_handoff_bindings import validate as validate_bindings
    validate_bindings(raw, messages)
    from memory.wsc_handoff_phase import validate as validate_phase
    validate_phase(raw, messages, required=require_phase)
    from memory.wsc_handoff_fact_disposition import validate as validate_fact_disposition
    validate_fact_disposition(raw, messages)
    from memory.wsc_handoff_progress import validate as validate_progress
    validate_progress(raw, messages)
    return parsed
