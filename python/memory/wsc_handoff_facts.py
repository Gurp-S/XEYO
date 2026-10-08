"""Exact source quotes for generated task facts, without semantic filtering."""
from synaptic.task_fact_sources import source_text, resolve


def committed_facts(sources):
    """Only the latest active successful declaration supplies verified slots.

    The whole tool body is never a fact source. Quotes are exact whole values
    in their original decision/constraint field, not arbitrary result text.
    """
    from synaptic.todo_snapshot import latest_todo_snapshot
    snapshot = latest_todo_snapshot(sources)
    if not snapshot.observed or not snapshot.active_count or snapshot.checkpoint is None:
        return {}
    index = snapshot.checkpoint_source
    if not 0 <= index < len(sources):
        return {}
    row = sources[index]
    identity = row.get("message_id") or row.get("id")
    if not identity or sum(str(item.get("message_id") or item.get("id")) == str(identity) for item in sources) != 1:
        return {}
    fields = {}
    for field in ("decisions", "constraints"):
        fields[field] = []
        for value in snapshot.checkpoint[field]:
            quote = value if isinstance(value, str) else value["quote"]
            if resolve(sources, str(identity), field, quote) is not None:
                fields[field].append(quote)
    return {str(identity): fields} if any(fields.values()) else {}


def validate_facts(raw, sources, *, require_citations=False):
    checkpoint = raw.get("checkpoint", {})
    by_id = {}
    for row in sources:
        identity = row.get("message_id") or row.get("id")
        if identity:
            by_id.setdefault(str(identity), []).append(row)
    context = checkpoint.get("context_message_ids", [])
    declared = committed_facts(sources)
    for field in ("decisions", "constraints"):
        for fact in checkpoint.get(field, []):
            if isinstance(fact, str) and not require_citations:
                continue  # Existing explicit model declarations remain compatible.
            if (not isinstance(fact, dict) or set(fact) != {"source_message_id", "quote"}
                    or not isinstance(fact["source_message_id"], str)
                    or not isinstance(fact["quote"], str) or not fact["quote"].strip()):
                raise ValueError("handoff_fact_citation_required")
            identity = fact["source_message_id"]
            matches = by_id.get(identity, [])
            if len(matches) != 1 or identity not in context:
                raise ValueError("handoff_fact_source_not_unique_or_bound")
            text = source_text(matches[0])
            exact_declared = fact["quote"] in declared.get(identity, {}).get(field, [])
            if not exact_declared and (text is None or fact["quote"] not in text):
                raise ValueError("handoff_fact_quote_not_in_source")
