"""Explicit model-declared applicability; chronology never infers meaning."""
from copy import deepcopy


def schema():
    scope = {"oneOf": [
        {"type": "object", "description": "Declared applicability throughout this task, independent of phase changes.",
         "properties": {"kind": {"const": "task"}}, "required": ["kind"], "additionalProperties": False},
        {"type": "object", "description": "Declared applicability only while the identified phase is current.",
         "properties": {"kind": {"const": "phase"}, "phase_id": {"type": "string", "minLength": 1}},
         "required": ["kind", "phase_id"], "additionalProperties": False}]}
    identities = {"type": "array", "maxItems": 16, "uniqueItems": True, "items": {"type": "string", "minLength": 1}}
    return {"type": "object", "additionalProperties": False,
        "description": "Declared current phase, phase provenance, active raw context identities and per-fact applicability. Historical provenance remains stored separately from active applicability.",
        "properties": {"current_phase_id": {"type": "string", "minLength": 1},
            "phases": {"type": "array", "minItems": 1, "maxItems": 16, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"id": {"type": "string", "minLength": 1, "description": "Stable declared phase identity across checkpoint updates."}, "name": {"type": "string", "minLength": 1},
                               "source_message_ids": dict(identities, minItems=1)},
                "required": ["id", "name", "source_message_ids"]}},
            "active_context_message_ids": identities,
            "fact_scopes": {"type": "object", "additionalProperties": False,
                "properties": {field: {"type": "array", "maxItems": 16, "items": scope} for field in ("decisions", "constraints")},
                "required": ["decisions", "constraints"]}},
        "required": ["current_phase_id", "phases", "active_context_message_ids", "fact_scopes"]}


def identities(value, *, nonempty=False):
    return (isinstance(value, list) and len(value) <= 16 and (bool(value) or not nonempty)
            and all(isinstance(uid, str) and uid.strip() for uid in value) and len(set(value)) == len(value))


def validate(value, checkpoint):
    if not isinstance(value, dict) or set(value) != {"current_phase_id", "phases", "active_context_message_ids", "fact_scopes"}:
        raise ValueError("invalid_task_phase_state")
    current, phases, active, scopes = (value[key] for key in ("current_phase_id", "phases", "active_context_message_ids", "fact_scopes"))
    if not isinstance(current, str) or not current.strip() or not isinstance(phases, list) or not 1 <= len(phases) <= 16:
        raise ValueError("invalid_task_phase_state")
    context = set(checkpoint["context_message_ids"])
    by_id = {}
    for phase in phases:
        if (not isinstance(phase, dict) or set(phase) != {"id", "name", "source_message_ids"}
                or not isinstance(phase["id"], str) or not phase["id"].strip() or phase["id"] in by_id
                or not isinstance(phase["name"], str) or not phase["name"].strip()
                or not identities(phase["source_message_ids"], nonempty=True)
                or not set(phase["source_message_ids"]) <= context):
            raise ValueError("invalid_task_phase_provenance")
        by_id[phase["id"]] = phase
    if current not in by_id or not identities(active) or not set(active) <= context:
        raise ValueError("invalid_task_phase_context")
    # Active raw context is a retrieval choice, not an applicability claim.
    # A historical source may also contain durable constraints needed now.
    if not isinstance(scopes, dict) or set(scopes) != {"decisions", "constraints"}:
        raise ValueError("invalid_task_fact_scopes")
    for field in ("decisions", "constraints"):
        if not isinstance(scopes[field], list) or len(scopes[field]) != len(checkpoint[field]):
            raise ValueError("invalid_task_fact_scopes")
        for scope in scopes[field]:
            if not isinstance(scope, dict) or not (
                    scope == {"kind": "task"} or set(scope) == {"kind", "phase_id"}
                    and scope["kind"] == "phase" and isinstance(scope["phase_id"], str) and scope["phase_id"] in by_id):
                raise ValueError("invalid_task_fact_scopes")
    return deepcopy(value)


def applicable(checkpoint, field):
    phase = checkpoint.get("phase_state")
    if phase is None:
        return checkpoint[field]
    return [fact for fact, scope in zip(checkpoint[field], phase["fact_scopes"][field])
            if scope["kind"] == "task" or scope["phase_id"] == phase["current_phase_id"]]


def active_context(checkpoint):
    phase = checkpoint.get("phase_state")
    return checkpoint["context_message_ids"] if phase is None else phase["active_context_message_ids"]
