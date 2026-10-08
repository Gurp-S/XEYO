"""Explicit task facts and source links, independent of historical requests."""
from __future__ import annotations

import hashlib
import json
MAX_DECLARATION_BYTES = 16_000
MAX_INLINE_SOURCE_BYTES = 32_000


def enabled():
    return True


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate(value):
    if not isinstance(value, dict) or set(value) - {"objective", "context_message_ids", "decisions", "constraints", "verification_call_ids"}:
        raise ValueError("invalid_task_checkpoint")
    result = {}
    objective = value.get("objective", "")
    if not isinstance(objective, str):
        raise ValueError("invalid_task_checkpoint_objective")
    result["objective"] = objective
    for key in ("context_message_ids", "decisions", "constraints", "verification_call_ids"):
        values = value.get(key, [])
        def valid(item):
            if isinstance(item, str):
                return bool(item.strip())
            return (key in {"decisions", "constraints"} and isinstance(item, dict)
                and set(item) == {"source_message_id", "quote"}
                and all(isinstance(item[k], str) and item[k].strip() for k in item))
        if (not isinstance(values, list) or len(values) > 16 or any(not valid(item) for item in values)):
            raise ValueError("invalid_task_checkpoint_" + key)
        result[key] = []
        seen = set()
        for item in values:
            identity = canonical(item)
            if identity not in seen:
                seen.add(identity)
                result[key].append(item)
    if len(canonical(result).encode("utf-8")) > MAX_DECLARATION_BYTES:
        raise ValueError("task_checkpoint_too_large")
    return result


def from_result(text):
    marker = "<task_checkpoint>"
    start = text.rfind(marker)
    while start >= 0:
        raw = text[start + len(marker):].lstrip()
        try:
            value, end = json.JSONDecoder().raw_decode(raw)
            if raw[end:].lstrip().startswith("</task_checkpoint>"):
                return validate(value)
        except (ValueError, RecursionError):
            pass
        start = text.rfind(marker, 0, start)
    return None


def project_state(messages, graph):
    """Only a committed TodoWrite receipt can publish an active checkpoint.

    No completion inference from prose or files. A declared decision remains a
    declaration; a referenced verification remains a tool execution receipt.
    """
    from synaptic.todo_snapshot import latest_todo_snapshot
    snapshot = latest_todo_snapshot(messages)
    if not snapshot.observed:
        return None, ()
    state = {"todo_source": snapshot.source, "todo_backing": snapshot.backing, "observed": True,
             "items": list(snapshot.records), "declared_objective": "", "declared_decisions": [], "declared_constraints": [],
             "context_sources": [], "deferred_sources": [], "verification_receipts": [], "unknown_sources": []}
    nodes = [snapshot.source]
    from synaptic.task_terminal import project as project_terminal
    terminal, terminal_nodes = project_terminal(snapshot, messages)
    if terminal is not None:
        state["terminal_task"] = terminal
        nodes.extend(terminal_nodes)
    if snapshot.active_count and snapshot.checkpoint is not None:
        from synaptic.task_execution import collect
        # A legacy todo receipt declares progress only, not an execution scope.
        # Heating subsequent history from that receipt would promote unrelated
        # old tool output into the current task without a context declaration.
        executions, sources = collect(messages, snapshot.checkpoint_source)
        state["subsequent_executions"] = executions
        nodes.extend(sources)
    # All-completed/explicit empty is a barrier, not a new task anchor.
    context = snapshot.checkpoint if snapshot.active_count else None
    if context is None:
        state["context_observed"] = False
        return state, tuple(nodes)
    state["context_observed"] = True
    state["checkpoint_source"] = snapshot.checkpoint_source
    if snapshot.checkpoint_source >= 0:
        nodes.append(snapshot.checkpoint_source)
    state["declared_decisions"] = context["decisions"]
    state["declared_constraints"] = context["constraints"]
    state["declared_objective"] = context["objective"]
    by_id = {}
    for index, message in enumerate(messages[:snapshot.source]):
        identity = message.get("id") or message.get("message_id")
        if identity:
            by_id.setdefault(str(identity), []).append(index)
    remaining = MAX_INLINE_SOURCE_BYTES
    for identity in context["context_message_ids"]:
        if identity == "@latest_user":
            # Explicit source alias, bound to the declaration receipt rather
            # than subsequent merge updates or later short follow-ups.
            boundary = snapshot.checkpoint_source
            eligible = [index for index, message in enumerate(messages[:boundary])
                        if message.get("role") in {"user", "human"}
                        and not any(message.get(key) for key in ("note_key", "note_kind", "note_retracted"))
                        and graph.node(index).kind == "user_text"]
            indices = eligible[-1:]
        else:
            indices = by_id.get(identity, [])
        if len(indices) != 1:
            state["unknown_sources"].append({"message_id": identity, "reason": "missing_or_ambiguous"})
            continue
        index = indices[0]
        node = graph.node(index)
        if node is None or node.kind not in {"user_text", "assistant_text"}:
            from synaptic.task_fact_sources import resolve
            bound = []
            for field in ("decisions", "constraints"):
                for fact in context[field]:
                    if isinstance(fact, dict) and fact["source_message_id"] == identity:
                        ancestry = resolve(messages[:snapshot.checkpoint_source], identity, field, fact["quote"])
                        if ancestry is not None:
                            bound.append({"field": field, "quote": fact["quote"], "sources": list(ancestry)})
                            nodes.extend(ancestry)
            if bound:
                state.setdefault("committed_fact_sources", []).append({"message_id": identity, "source": index, "facts": bound})
                continue
            state["unknown_sources"].append({"message_id": identity, "reason": "not_text"})
            continue
        size = len(node.text.encode("utf-8"))
        if size > remaining:
            from synaptic.source_description import describe
            state["deferred_sources"].append({"message_id": identity, "source": index,
                "reason": "inline_capacity", "payload_bytes": size, **describe(node)})
            nodes.append(index)
            continue
        remaining -= size
        state["context_sources"].append({"message_id": identity, "source": index, "text": node.text})
        nodes.append(index)
    from synaptic.task_verification import collect as collect_verification
    receipts, unknown, verification_nodes = collect_verification(
        messages, context["verification_call_ids"], snapshot.source)
    state["verification_receipts"] = receipts
    state["unknown_sources"].extend(unknown)
    nodes.extend(verification_nodes)
    return state, tuple(dict.fromkeys(nodes))


def pin(messages, graph):
    if not enabled():
        return None, ""
    from synaptic.types import Pin
    state, nodes = project_state(messages, graph)
    if state is None:
        return None, ""
    body = canonical(state)
    return Pin("task_checkpoint", "任务状态快照", body, nodes=nodes), hashlib.sha256(body.encode("utf-8")).hexdigest()


def restore_receipts(emitted, messages, base, frozen_attr):
    """Keep bounded committed task receipts in the unfrozen tail, after C0.

    A later true fold absorbs the state in a checkpoint pin. This function
    cannot rewrite results inside an already frozen emission region.
    """
    if not enabled():
        return emitted
    from synaptic.todo_snapshot import latest_todo_snapshot
    from synaptic.textutil import tool_result_blocks
    snapshot = latest_todo_snapshot(messages)
    if not snapshot.observed:
        return emitted
    targets = {snapshot.source}
    checkpoint = snapshot.checkpoint if snapshot.active_count else None
    if checkpoint:
        if snapshot.checkpoint_source >= 0:
            targets.add(snapshot.checkpoint_source)
        uids = set(checkpoint["verification_call_ids"])
        targets.update(i for i, message in enumerate(messages)
            if any(isinstance(result.get("tool_use_id"), (str, int))
                   and result.get("tool_use_id") in uids for result in tool_result_blocks(message)))
    for index in targets:
        position = index - base + 1
        if index < max(base, frozen_attr) or position >= len(emitted):
            continue
        raw = messages[index]
        if len(canonical(raw).encode("utf-8")) <= MAX_INLINE_SOURCE_BYTES:
            emitted[position] = raw
    return emitted
