"""One fact/scope wire record, compiled to the existing durable declaration.

Only representation changes here. Applicability, sources, phases and lifecycle
remain model declarations validated by the native Guard. No scope is inferred.
"""
from copy import deepcopy

FIELDS = ("decisions", "constraints")


def schema(native):
    result = deepcopy(native)
    checkpoint = result["input_schema"]["properties"]["checkpoint"]
    phase = checkpoint["properties"].get("phase_state")
    if phase is None:
        return result
    scopes = phase["properties"].pop("fact_scopes")
    phase["required"].remove("fact_scopes")
    for field in FIELDS:
        item = checkpoint["properties"][field]["items"]
        item["properties"]["scope"] = deepcopy(scopes["properties"][field]["items"])
        item["required"].append("scope")
    return result


def to_native(raw):
    """Accept either whole legacy or whole inline encoding, never both.

    Legacy validity and all semantic/provenance checks belong to the existing
    validator. The caller keeps the original raw ToolUse for provider replay.
    """
    from memory.wsc_handoff_validation import StateError
    result = deepcopy(raw)
    if not isinstance(result, dict) or not isinstance(result.get("checkpoint"), dict):
        return result
    checkpoint = result["checkpoint"]
    phase = checkpoint.get("phase_state")
    attached = any(isinstance(fact, dict) and "scope" in fact
                   for field in FIELDS for fact in checkpoint.get(field, [])
                   ) if all(isinstance(checkpoint.get(field, []), list) for field in FIELDS) else False
    if isinstance(phase, dict) and "fact_scopes" in phase:
        if attached:
            raise StateError("handoff_invalid_state", state_error="scoped_fact_authority_duplicated")
        return result
    if not attached and phase is None:
        return result
    if not isinstance(phase, dict):
        raise StateError("handoff_invalid_state", state_error="scoped_fact_phase_missing")
    tags = {}
    for field in FIELDS:
        facts = checkpoint.get(field, [])
        if not isinstance(facts, list) or any(
                not isinstance(fact, dict) or set(fact) != {"source_message_id", "quote", "scope"}
                for fact in facts):
            raise StateError("handoff_invalid_state", state_error="scoped_fact_schema_invalid",
                             field="$.checkpoint." + field)
        tags[field] = [deepcopy(fact["scope"]) for fact in facts]
        if field in checkpoint:
            checkpoint[field] = [{key: fact[key] for key in ("source_message_id", "quote")} for fact in facts]
    phase["fact_scopes"] = tags
    return result
