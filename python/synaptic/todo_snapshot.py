"""Select observed TodoWrite state; legacy transcripts retain input fallback.

No second todo store or merge implementation: successful tool output already
contains the complete list, including members untouched by a merge.
"""
from dataclasses import dataclass
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
            if result.get("is_error"):
                continue
            payload = _payload(tool_result_text(result))
            if payload is not None:
                labels, count = summarize(payload)
                backing = idx if input_backs_state(input_items, payload) else result_idx
                snapshot = TodoSnapshot(labels, result_idx, backing, observed=True, active_count=count)
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
    if any(state.observed for state in candidates):
        return max(settled, key=lambda entry: entry[0])[1]
    return max(candidates, key=lambda state: state.source, default=TodoSnapshot())
