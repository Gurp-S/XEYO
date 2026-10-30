"""Expose stored model-record identity without certifying its interpretation."""
from copy import deepcopy
import json

from .contracts import require


def recorded_items(items, records, *, working_state_index):
    """Preserve selected text and evidence; distinguish revisions from observations.

    Record provenance comes from the bound understanding index, never guessed
    from prose. Historical native messages and all evidence values stay intact.
    """
    by_ref = {record["ref"]: record for record in records}
    require(len(by_ref) == len(records), "recorded_understanding_identity_ambiguous")
    result = deepcopy(items)
    require(type(working_state_index) is int and 0 <= working_state_index < len(result),
            "recorded_working_state_index_invalid")
    item = result[working_state_index]
    content = item.get("content", [])
    require(item.get("type") == "message" and item.get("role") == "assistant"
            and len(content) == 1 and content[0].get("type") == "output_text",
            "recorded_understanding_view_shape_invalid")
    facts = json.loads(content[0]["text"])
    require(isinstance(facts, dict) and facts.get("kind") == "working_state"
            and isinstance(facts.get("understandings"), list), "recorded_understanding_view_shape_invalid")
    model_records = []
    for value in facts["understandings"]:
        source = by_ref.get(value["ref"])
        require(source is not None and all(value[k] == source[k] for k in ("text", "kind", "scope"))
                and [loc["source_id"] for loc in value["sources"]] == source["sources"],
                "recorded_understanding_binding_changed")
        model_records.append({"ref": value["ref"], "producer": source["producer"],
            "previous": source["previous"], "kind": value["kind"], "text": value["text"],
            "scope": value["scope"], "sources": value["sources"]})
    # Stable explicit order: recorded interpretation followed by its available
    # observations. JSON key sorting would move understandings to the tail.
    projected = {"kind": "working_state", "model_records": model_records,
                 **{k: v for k, v in facts.items() if k not in {"kind", "understandings"}}}
    content[0]["text"] = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    return result
