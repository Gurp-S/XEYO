"""Explicit, base-anchored retirement of declared task-wide facts.

This verifies declared transitions and provenance, not the meaning of events.
Historical phase facts are not promoted to task facts by this contract.
"""
from synaptic.todo_snapshot import latest_todo_snapshot
from synaptic.task_fact_sources import source_text


class DispositionError(ValueError):
    def __init__(self, code, **facts):
        super().__init__(code)
        self.detail = {"error": code, **facts}


def task_facts(checkpoint):
    phase = checkpoint.get("phase_state")
    if phase is None:
        return []  # Legacy declarations have no explicit lifetime claim.
    return [{"field": field, "quote": fact if isinstance(fact, str) else fact["quote"]}
            for field in ("decisions", "constraints")
            for fact, scope in zip(checkpoint[field], phase["fact_scopes"][field])
            if scope["kind"] == "task"]


def basis(sources):
    prior = latest_todo_snapshot(sources)
    if not prior.observed or not prior.active_count or prior.checkpoint is None:
        return None
    facts = task_facts(prior.checkpoint)
    if not facts:
        return None
    row = sources[prior.checkpoint_source]
    uid = row.get("message_id") or row.get("id")
    if not uid or sum(str(r.get("message_id") or r.get("id")) == str(uid) for r in sources) != 1:
        raise DispositionError("handoff_task_fact_base_not_unique")
    return {"base_checkpoint_message_id": str(uid), "task_facts": facts}


def schema():
    return {"type": "object", "additionalProperties": False,
        "description": "Declared retirement of omitted or phase-scoped previously task-wide facts, anchored to the last checkpoint and subsequent text events.",
        "properties": {"base_checkpoint_message_id": {"type": "string"},
            "retired_facts": {"type": "array", "maxItems": 32, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"field": {"enum": ["decisions", "constraints"]},
                    "quote": {"type": "string", "minLength": 1},
                    "event_message_ids": {"type": "array", "minItems": 1, "maxItems": 16,
                        "items": {"type": "string"}}},
                "required": ["field", "quote", "event_message_ids"]}}},
        "required": ["base_checkpoint_message_id", "retired_facts"]}


def validate(raw, sources):
    prior = basis(sources)
    disposition = raw.get("fact_disposition")
    if prior is None:
        if disposition is not None:
            raise DispositionError("handoff_task_fact_disposition_without_base")
        return
    active = any(item.get("status") != "completed" for item in raw.get("todos", []))
    if not active and disposition is None:
        return  # Explicit terminal state is the existing task barrier.
    keys = lambda records: {(r["field"], r["quote"]) for r in records}
    missing = keys(prior["task_facts"]) - keys(task_facts(raw["checkpoint"])) if active else set()
    if disposition is None:
        if missing:
            raise DispositionError("handoff_task_fact_disposition_missing", **prior,
                omitted_task_facts=[{"field": f, "quote": q} for f, q in sorted(missing)])
        return
    if (not isinstance(disposition, dict)
            or set(disposition) != {"base_checkpoint_message_id", "retired_facts"}
            or not isinstance(disposition["retired_facts"], list)
            or len(disposition["retired_facts"]) > 32):
        raise DispositionError("handoff_task_fact_disposition_invalid")
    if disposition["base_checkpoint_message_id"] != prior["base_checkpoint_message_id"]:
        raise DispositionError("handoff_task_fact_disposition_stale_base", **prior)
    indices = {}
    for index, row in enumerate(sources):
        uid = row.get("message_id") or row.get("id")
        if uid: indices.setdefault(str(uid), []).append(index)
    base_index = indices[prior["base_checkpoint_message_id"]][0]
    retired = []
    for record in disposition["retired_facts"]:
        if (not isinstance(record, dict) or set(record) != {"field", "quote", "event_message_ids"}
                or not isinstance(record["field"], str) or record["field"] not in {"decisions", "constraints"}
                or not isinstance(record["quote"], str)
                or not isinstance(record["event_message_ids"], list)
                or not 1 <= len(record["event_message_ids"]) <= 16
                or any(not isinstance(uid, str) for uid in record["event_message_ids"])
                or len(set(record["event_message_ids"])) != len(record["event_message_ids"])):
            raise DispositionError("handoff_task_fact_disposition_invalid")
        retired.append((record["field"], record["quote"]))
        for uid in record["event_message_ids"]:
            matches = indices.get(uid, [])
            if (len(matches) != 1 or matches[0] <= base_index
                    or sources[matches[0]].get("role") not in {"user", "human", "assistant"}
                    or source_text(sources[matches[0]]) is None):
                raise DispositionError("handoff_task_fact_retirement_event_invalid", source_message_id=uid)
    if len(set(retired)) != len(retired) or set(retired) != missing:
        raise DispositionError("handoff_task_fact_disposition_mismatch", **prior,
            omitted_task_facts=[{"field": f, "quote": q} for f, q in sorted(missing)])
