"""Whole text events after a committed checkpoint, without semantic inference.

This is the production request materializer. It runs before normalization and
capacity counting; the old experimental transport injector remains unchanged.
"""
import json

from synaptic.task_fact_sources import source_text
from synaptic.todo_snapshot import latest_todo_snapshot

MAX_BYTES = 16_000


def materialize(sources, *, max_bytes=MAX_BYTES, admit=None):
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("handoff_delta_budget_invalid")
    snapshot = latest_todo_snapshot(sources)
    base = snapshot.checkpoint_source if snapshot.observed else -1
    if snapshot.checkpoint is None or not 0 <= base < len(sources):
        return None
    candidates = []
    for index, row in enumerate(sources[base + 1:], base + 1):
        if any(row.get(key) for key in ("note_key", "note_kind", "note_retracted")):
            continue
        text = source_text(row)
        identity = row.get("message_id") or row.get("id")
        if text is not None and identity:
            candidates.append({"source": index, "message_id": str(identity),
                               "role": row.get("role"), "content": text, "text_complete": True})
    if not candidates:
        return None
    identities = [str(row.get("message_id") or row.get("id")) for row in sources
                  if row.get("message_id") or row.get("id")]
    if len(identities) != len(set(identities)):
        raise ValueError("handoff_delta_source_ambiguous")
    envelope = {"base_checkpoint_message_id": sources[base].get("message_id") or sources[base].get("id"),
                "sources": [], "deferred_message_ids": [],
                "source_records_after_checkpoint": len(sources) - base - 1}
    # Optional evidence cannot invalidate an otherwise admitted request merely
    # because even its deferred-identity envelope has no remaining capacity.
    # The existing catalog/read path still exposes these source identities.
    deferred_only = dict(envelope, deferred_message_ids=[r["message_id"] for r in candidates])
    if admit is not None and not admit(deferred_only):
        return None
    selected, deferred, used = [], [], 0
    for position in reversed(range(len(candidates))):
        record = candidates[position]
        size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        pending = [item["message_id"] for item in candidates[:position]]
        candidate = dict(envelope, sources=list(reversed([*selected, record])),
                         deferred_message_ids=[*pending, *reversed(deferred)])
        fits = used + size <= max_bytes and (admit is None or admit(candidate))
        if fits:
            selected.append(record)
            used += size
        else:
            deferred.append(record["message_id"])
    return dict(envelope, sources=list(reversed(selected)), deferred_message_ids=list(reversed(deferred)))
