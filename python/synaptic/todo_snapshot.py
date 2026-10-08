"""Select observed TodoWrite state; legacy transcripts retain input fallback.

No second todo store or merge implementation: successful tool output already
contains the complete list, including members untouched by a merge.
"""
from dataclasses import dataclass, replace
import json

from synaptic.textutil import tool_result_blocks, tool_result_text, tool_use_blocks
from synaptic.graph import result_is_error
from synaptic.todo_fields import input_backs_state, summarize


@dataclass(frozen=True)
class TodoSnapshot:
    items: tuple[str, ...] = ()
    source: int = -1
    backing: int = -1
    observed: bool = False
    active_count: int | None = 0
    records: tuple[dict, ...] = ()
    checkpoint: dict | None = None
    checkpoint_source: int = -1
    terminal: dict | None = None


def _payload(text):
    # Decode JSON before locating the closing tag: literal tags in a content
    # string are data, not delimiters.
    marker = "<todo_list>"
    start = text.rfind(marker)
    while start >= 0:
        raw = text[start + len(marker):].lstrip()
        try:
            value, end = json.JSONDecoder().raw_decode(raw)
        except (ValueError, RecursionError):
            value = None
            end = 0
        if isinstance(value, list) and raw[end:].lstrip().startswith("</todo_list>"):
            if all(isinstance(item, dict) and isinstance(item.get("content"), str)
                   and isinstance(item.get("status"), str)
                   and item["status"] in {"pending", "in_progress", "completed"}
                   for item in value):
                return value
        start = text.rfind(marker, 0, start)
    return None


def latest_todo_snapshot(messages):
    calls = {}
    outcomes = {}
    for idx, message in enumerate(messages):
        for use in tool_use_blocks(message):
            if use.get("name") == "TodoWrite":
                uid = use.get("id")
                if isinstance(uid, (str, int)) and uid:
                    calls.setdefault(uid, []).append((idx, use))
        for result in tool_result_blocks(message):
            uid = result.get("tool_use_id")
            if isinstance(uid, (str, int)) and uid:
                outcomes.setdefault(uid, []).append((idx, result))
    candidates = []
    settled = []
    committed_inputs = {}
    for uid, uses in calls.items():
        # Ambiguous duplicate IDs cannot establish authoritative provenance.
        if len(uses) != 1:
            continue
        idx, use = uses[0]
        inp = use.get("input")
        input_items = inp.get("todos", inp.get("items")) if isinstance(inp, dict) else None
        results = [(i, r) for i, r in outcomes.get(uid, ()) if i > idx]
        if len(results) == 1:
            result_idx, result = results[0]
            execution = result.get("execution")
            if execution is not None and not isinstance(execution, dict):
                continue
            execution = execution or {}
            if result_is_error(result) or execution.get("status") in {"error", "cancelled"} or execution.get("complete") is False:
                continue
            payload = _payload(tool_result_text(result))
            if payload is not None:
                labels, count = summarize(payload)
                backing = idx if input_backs_state(input_items, payload) else result_idx
                from synaptic.task_checkpoint import from_result
                snapshot = TodoSnapshot(labels, result_idx, backing, observed=True, active_count=count,
                    records=tuple(payload), checkpoint=from_result(tool_result_text(result)), checkpoint_source=result_idx)
                committed_inputs[result_idx] = inp
                candidates.append(snapshot)
                settled.append((result_idx, snapshot))
                continue
            if result_is_error(result):
                continue
        if isinstance(inp, dict):
            items = input_items
            if isinstance(items, (list, str)):
                labels, count = summarize(items)
                snapshot = TodoSnapshot(labels, idx, idx, active_count=count)
                candidates.append(snapshot)
                if len(results) == 1:
                    settled.append((results[0][0], snapshot))
    # Once structured observations exist, a not-yet-finished intent cannot
    # replace committed state. Legacy completed receipts keep input fallback.
    from synaptic.task_checkpoint import enabled
    if enabled():
        previous = TodoSnapshot()
        for state in sorted((state for state in candidates if state.observed), key=lambda state: state.source):
            inp = committed_inputs.get(state.source) or {}
            old_ids = {item.get("id") for item in previous.records
                       if item.get("status") != "completed" and isinstance(item.get("id"), str) and item.get("id")}
            new_ids = {item.get("id") for item in state.records
                       if item.get("status") != "completed" and isinstance(item.get("id"), str) and item.get("id")}
            if (state.checkpoint is None and isinstance(inp, dict) and inp.get("merge") is True
                    and state.active_count and old_ids.intersection(new_ids)):
                state = replace(state, checkpoint=previous.checkpoint, checkpoint_source=previous.checkpoint_source)
            if state.active_count == 0 and state.checkpoint is not None:
                state = replace(state, terminal={"kind": "completed" if state.records else "cleared",
                    "objective": state.checkpoint.get("objective", ""),
                    "checkpoint_source": state.checkpoint_source, "commit_source": state.source,
                    "verification_call_ids": list(state.checkpoint.get("verification_call_ids", [])),
                    "step_ids": [item.get("id") for item in state.records]})
            elif state.active_count == 0 and previous.checkpoint is not None:
                completed_ids = {item.get("id") for item in state.records if item.get("status") == "completed"}
                kind = ("cleared" if not state.records else
                        "completed" if old_ids and old_ids.issubset(completed_ids) else "replaced")
                state = replace(state, terminal={"kind": kind,
                    "objective": previous.checkpoint.get("objective", ""),
                    "checkpoint_source": previous.checkpoint_source,
                    "verification_call_ids": list(previous.checkpoint.get("verification_call_ids", [])),
                    "commit_source": state.source,
                    "step_ids": [item.get("id") for item in previous.records]})
            elif (state.active_count == 0 and previous.terminal is not None
                    and {item.get("id") for item in state.records} == {item.get("id") for item in previous.records}):
                state = replace(state, terminal=previous.terminal)
            previous = state
        return previous
    if any(state.observed for state in candidates):
        return max(settled, key=lambda entry: entry[0])[1]
    return max(candidates, key=lambda state: state.source, default=TodoSnapshot())
