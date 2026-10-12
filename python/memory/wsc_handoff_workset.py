"""Exact, bounded active source text for the isolated handoff generation call."""
import json

from memory.wsc_handoff_bindings import basis
from synaptic.task_fact_sources import source_text

MAX_WORKSET_BYTES = 48_000


def materialize(sources, *, admit=None):
    prior = basis(sources)
    if prior is None:
        return {"sources": [], "deferred_message_ids": []}
    by_id = {}
    for row in sources:
        uid = row.get("message_id") or row.get("id")
        if uid:
            by_id.setdefault(str(uid), []).append(row)
    selected, deferred = [], []
    size = 0
    identities = prior["bound_context_message_ids"]
    for position, uid in enumerate(identities):
        matches = by_id.get(uid, [])
        text = source_text(matches[0]) if len(matches) == 1 else None
        if text is None:
            deferred.append(uid)
            continue
        record = {"message_id": uid, "content": text, "text_complete": True}
        encoded = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        fits = (admit(selected + [record], deferred + identities[position + 1:])
                if admit is not None else size + encoded <= MAX_WORKSET_BYTES)
        if not fits:
            deferred.append(uid)
            continue
        selected.append(record)
        size += encoded
    return {"sources": selected, "deferred_message_ids": deferred}
