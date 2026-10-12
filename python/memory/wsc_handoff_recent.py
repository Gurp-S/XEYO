"""Exact recent text evidence for a dedicated declaration, not active authority."""
from collections import Counter
import json

from synaptic.task_fact_sources import source_text

PER_ROLE = 8
MAX_BYTES = 48_000


def materialize(sources, *, admit=None):
    counts = Counter(str(row.get("message_id") or row.get("id")) for row in sources)
    candidates, used = [], {"user": 0, "assistant": 0}
    for index in reversed(range(len(sources))):
        row = sources[index]
        role = "user" if row.get("role") == "human" else row.get("role")
        uid = row.get("message_id") or row.get("id")
        text = source_text(row)
        if role not in used or used[role] >= PER_ROLE or not uid or text is None:
            continue
        used[role] += 1
        candidates.append((index, str(uid), role, text))
    selected, deferred, size = [], [], 0
    for position, (index, uid, role, text) in enumerate(candidates):
        record = {"source": index, "message_id": uid, "role": role, "content": text, "text_complete": True}
        encoded = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if counts[uid] != 1 or size + encoded > MAX_BYTES:
            deferred.append(uid)
            continue
        remaining = [item[1] for item in candidates[position+1:]]
        if admit is not None and not admit(selected + [record], deferred + remaining):
            deferred.append(uid)
            continue
        selected.append(record)
        size += encoded
    return {"sources": sorted(selected, key=lambda row: row["source"]),
            "deferred_message_ids": list(dict.fromkeys(deferred))}
