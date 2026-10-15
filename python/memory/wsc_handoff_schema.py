"""Executable source-bound declaration protocol, without semantic inference."""
from copy import deepcopy
import json


def source_schema(schema, sources, catalog=None, *, scope_protocol=False):
    """Separate citation namespaces structurally; IDs are supplied facts."""
    from memory.wsc_handoff_catalog import Catalog, INITIAL_RECORDS
    catalog = catalog or Catalog(sources)
    identities = catalog.initial()
    message_ids, verification_ids = catalog.unique_ids, catalog.verification_ids
    bounded_enums = len(sources) <= INITIAL_RECORDS
    constrained = deepcopy(schema)
    constrained["description"] = "Stores a complete task declaration in one object containing todos and checkpoint. Progress is declared; verification references identify observed tool invocations."
    constrained["input_schema"]["required"] = ["todos", "checkpoint"]
    constrained["input_schema"]["additionalProperties"] = False
    constrained["input_schema"]["properties"]["merge"] = {"type": "boolean", "const": False, "default": False}
    item = constrained["input_schema"]["properties"]["todos"]["items"]["properties"]
    for field in ("id", "content", "activeForm"):
        item[field].update(minLength=1, pattern=r"\S")
    item["id"]["description"] = "Stable item identity."
    # Citation provenance is mandatory even when the optional phase protocol
    # supplies an additional active-context list. The two have distinct roles.
    constrained["input_schema"]["properties"]["checkpoint"]["required"] = ["context_message_ids"]
    from memory.wsc_handoff_fact_disposition import basis as fact_basis, schema as disposition_schema
    prior_facts = fact_basis(sources)
    from memory.wsc_handoff_bindings import basis
    prior = basis(sources)
    phase_required = scope_protocol or prior_facts is not None or (prior or {}).get('phase_state') is not None
    if phase_required:
        from synaptic.task_phase import schema as phase_schema
        constrained["input_schema"]["properties"]["checkpoint"]["properties"]["phase_state"] = phase_schema()
        if prior_facts is not None:
            constrained["input_schema"]["properties"]["fact_disposition"] = disposition_schema()
            constrained["description"] += " Previous declared task-wide facts=" + json.dumps(prior_facts, ensure_ascii=False)
    # These are the same active-context preconditions enforced by validate().
    # Terminal/empty declarations retain the existing empty-objective barrier.
    active_checkpoint = {"required": ["objective", "context_message_ids"], "properties": {
        "objective": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "context_message_ids": {"minItems": 1}}}
    if phase_required:
        active_checkpoint["required"].append("phase_state")
    constrained["input_schema"]["allOf"] = [{"if": {"properties": {"todos": {"contains": {
        "properties": {"status": {"enum": ["pending", "in_progress"]}}, "required": ["status"]}}}},
        "then": {"properties": {"checkpoint": active_checkpoint}}}]
    if prior is not None:
        constrained["input_schema"]["properties"]["context_disposition"] = {
            "type": "object", "description": "Explicit disposition of previously committed context identities omitted from this active declaration.",
            "properties": {"base_checkpoint_message_id": {"type": "string"},
                "retired_context_message_ids": {"type": "array", "maxItems": 16, "items": {"type": "string"}}},
            "required": ["base_checkpoint_message_id", "retired_context_message_ids"], "additionalProperties": False}
    properties = constrained["input_schema"]["properties"]["checkpoint"]["properties"]
    for field, values, description in (
        ("context_message_ids", message_ids, "Source message identities (message_id namespace)."),
        ("verification_call_ids", verification_ids, "Observed tool invocation identities (tool_call_ids namespace).")):
        properties[field] = {"type": "array", "maxItems": len(values) if field == "verification_call_ids" else min(16, len(values)),
                             "description": description, "items": {"type": "string"}}
        if values and bounded_enums: properties[field]["items"]["enum"] = values
    from memory.wsc_handoff_facts import source_text, committed_facts
    declarations = committed_facts(sources)
    unique_ids = set(message_ids)
    fact_ids = [str(row.get("message_id") or row.get("id")) for row in sources
                if source_text(row) is not None and str(row.get("message_id") or row.get("id")) in unique_ids]
    fact_ids.extend(uid for uid in declarations if uid not in fact_ids)
    for field in ("decisions", "constraints"):
        identity_schema = {"type": "string"}
        if fact_ids and bounded_enums: identity_schema["enum"] = fact_ids
        properties[field] = {"type": "array", "maxItems": 16 if fact_ids else 0,
            "description": "Exact quotes from task text or whole values from the same field of the latest active committed_task_fields; source message identities identify provenance.",
            "items": {"type": "object", "properties": {
                "source_message_id": identity_schema, "quote": {"type": "string", "minLength": 1}},
                "required": ["source_message_id", "quote"], "additionalProperties": False}}
    from memory.wsc_handoff_scope_encoding import schema as scope_schema
    return scope_schema(constrained), identities
