"""A declared progress change has a fresh source, not just old references.

This is provenance of a declaration, not proof that its status is correct.
Only explicitly scoped task declarations adopt this contract.
"""
from synaptic.todo_snapshot import latest_todo_snapshot
from memory.wsc_handoff_phase import observed_source


class ProgressError(ValueError):
    def __init__(self, code, **facts):
        super().__init__(code)
        self.detail = {"error": code, **facts}


def validate(raw, sources):
    prior = latest_todo_snapshot(sources)
    if (not prior.observed or not prior.active_count or prior.checkpoint is None
            or "phase_state" not in prior.checkpoint):
        return
    statuses = {item.get("id"): item.get("status") for item in prior.records}
    changes = [{"id": item["id"], "from_status": statuses[item["id"]], "to_status": item["status"]}
               for item in raw.get("todos", [])
               if item.get("id") in statuses and item.get("status") != statuses[item["id"]]]
    declared_ids = {item.get("id") for item in raw.get("todos", [])}
    # Omission is also a progress transition. Otherwise an empty handoff can
    # erase every unfinished step without the witness required for completion.
    changes.extend({"id": uid, "from_status": status, "to_status": "absent"}
                   for uid, status in statuses.items()
                   if status != "completed" and uid not in declared_ids)
    if not changes:
        return
    cp = raw["checkpoint"]
    context = set(cp.get("context_message_ids", []))
    verification = set(cp.get("verification_call_ids", []))
    indices = {}
    for i, row in enumerate(sources):
        uid = row.get("message_id") or row.get("id")
        if uid: indices.setdefault(str(uid), []).append(i)
    for i in range(prior.checkpoint_source + 1, len(sources)):
        row = sources[i]
        uid = str(row.get("message_id") or row.get("id") or "")
        if any(row.get(key) for key in ("note_key", "note_kind", "note_retracted")):
            continue
        if uid in context and len(indices.get(uid, [])) == 1 and observed_source(sources, i):
            return
    # A late actual result can postdate the checkpoint even when its original
    # invocation predates it. Freshness belongs to the effective receipt.
    from synaptic.task_verification import collect
    receipts, _unknown, _nodes = collect(sources, verification, len(sources), inline_bytes=0)
    if any(receipt['source'] > prior.checkpoint_source
           and observed_source(sources, receipt['source']) for receipt in receipts):
        return
    base = sources[prior.checkpoint_source]
    events = []
    for i in range(prior.checkpoint_source + 1, len(sources)):
        row = sources[i]
        uid = str(row.get("message_id") or row.get("id") or "")
        if (uid and len(indices.get(uid, [])) == 1 and observed_source(sources, i)
                and not any(row.get(key) for key in ("note_key", "note_kind", "note_retracted"))):
            events.append({"source": i, "message_id": uid, "role": row.get("role")})
    raise ProgressError("handoff_progress_source_missing",
        base_checkpoint_message_id=base.get("message_id") or base.get("id"), changes=changes,
        observed_events_after_checkpoint=events[-16:])
