"""Original text ancestors of committed facts, without semantic selection."""
from collections import Counter
import json

from synaptic.task_fact_sources import resolve, source_text
from synaptic.task_phase import applicable
from synaptic.todo_snapshot import latest_todo_snapshot

MAX_BYTES = 16_000


def ancestry(sources):
    snapshot = latest_todo_snapshot(sources)
    if not snapshot.observed or not snapshot.active_count or snapshot.checkpoint is None:
        return [], []
    base = snapshot.checkpoint_source
    if not 0 <= base < len(sources):
        return [], []
    identity = sources[base].get("message_id") or sources[base].get("id")
    counts = Counter(str(r.get("message_id") or r.get("id")) for r in sources
                     if r.get("message_id") or r.get("id"))
    records, unresolved, seen = [], [], set()
    for field in ("decisions", "constraints"):
        for index, fact in enumerate(applicable(snapshot.checkpoint, field)):
            quote = fact if isinstance(fact, str) else fact["quote"]
            chain = resolve(sources, str(identity), field, quote) if identity and counts[str(identity)] == 1 else None
            original = sources[chain[-1]] if chain else None
            text = source_text(original) if original else None
            uid = (original.get("message_id") or original.get("id")) if original else None
            if text is None or not uid or counts[str(uid)] != 1 or original.get("note_retracted"):
                unresolved.append({"field": field, "index": index, "reason": "original_text_ancestor_unavailable"})
                continue
            uid = str(uid)
            if uid not in seen:
                seen.add(uid)
                records.append({"source": chain[-1], "message_id": uid, "role": original.get("role"),
                                "content": text, "text_complete": True})
    return records, unresolved


def materialize(sources, *, presented_ids=(), admit=None, max_bytes=MAX_BYTES):
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("handoff_anchor_budget_invalid")
    records, unresolved = ancestry(sources)
    presented = set(presented_ids)
    records = [row for row in records if row["message_id"] not in presented]
    if not records:
        return None
    envelope = {"sources": [], "deferred_message_ids": [], "unresolved_facts": unresolved}
    if admit is not None and not admit(dict(envelope, deferred_message_ids=[r["message_id"] for r in records])):
        return None
    selected, deferred, used = [], [], 0
    for index, record in enumerate(records):
        size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        pending = [row["message_id"] for row in records[index + 1:]]
        candidate = dict(envelope, sources=[*selected, record], deferred_message_ids=[*deferred, *pending])
        if used + size <= max_bytes and (admit is None or admit(candidate)):
            selected.append(record)
            used += size
        else:
            deferred.append(record["message_id"])
    return dict(envelope, sources=selected, deferred_message_ids=deferred)
