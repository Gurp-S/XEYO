"""Observed receipts after a checkpoint; chronology is not task association."""
import json
from synaptic.textutil import tool_use_blocks, tool_result_blocks, tool_result_text


def collect(messages, after, *, limit=16, inline_bytes=16000):
    calls, results = {}, []
    for index, message in enumerate(messages):
        for use in tool_use_blocks(message):
            uid = use.get("id")
            if isinstance(uid, (str, int)) and uid:
                calls.setdefault(uid, []).append((index, use))
        if index > after:
            for result in tool_result_blocks(message):
                uid = result.get("tool_use_id")
                if isinstance(uid, (str, int)) and uid:
                    results.append((index, result))
    sources, observations = [], []
    for index, result in results:
        uid = result["tool_use_id"]
        uses = [(i, use) for i, use in calls.get(uid, []) if i < index]
        if len(uses) == 1 and uses[0][1].get("name") == "TodoWrite":
            continue
        sources.append(index)
        sources.extend(i for i, _ in uses)
        observations.append((index, result, uses))
    receipts = []
    remaining = inline_bytes
    # Recent observations get inline capacity; all sources remain recoverable.
    for index, result, uses in reversed(observations[-limit:]):
        unique = len(uses) == 1 and sum(r.get("tool_use_id") == result["tool_use_id"] for _, r in results) == 1
        entry = {"call_id": result["tool_use_id"], "source": index, "provenance_unique": unique,
                 "task_association": "undeclared", "is_error": result.get("is_error"),
                 "execution": result.get("execution"), "tool": uses[0][1].get("name") if unique else None}
        payload = {"input": uses[0][1].get("input") if unique else None,
                   "output": tool_result_text(result)}
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if size <= remaining:
            entry.update(payload)
            entry["inline"] = True
            remaining -= size
        else:
            entry.update(inline=False, payload_bytes=size)
        receipts.append(entry)
    return {"observed_count": len(observations), "inline_or_indexed": list(reversed(receipts)),
            "display_limit": limit}, tuple(dict.fromkeys(sources))
