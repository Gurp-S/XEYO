"""Selection of mechanically bound public spans instead of regenerated quotes.

Every non-opaque public character is offered, in source order. No ranking,
similarity, semantic slicing, truncation, or live-file lookup occurs here.
"""
from dataclasses import replace
from hashlib import sha256

from .contracts import Generated, Usage, WSCError, encode, require
from .excerpts import Excerpt
from .generation import string_list
from .quote_selection import SelectionDraft, compile_selection, selection_material
from .span_boundaries import ranges
from .span_selection_facts import span_facts


def _catalog(material, max_chars, boundary_policy="fixed"):
    require(type(max_chars) is int and max_chars > 0, "span_size_invalid")
    require(boundary_policy in {"fixed", "word"}, "span_boundary_policy_invalid")
    offered = selection_material(material)
    if 'selection_facts' in offered:
        offered['selection_facts'] = span_facts(offered['selection_facts'])
    source_ids = {event["seq"]: event["id"] for event in material["events"]}
    catalog, events = {}, []
    for event in offered["events"]:
        text, blocks = event["text"], []
        if isinstance(text, str):
            for start, end in ranges(text, max_chars, policy=boundary_policy):
                value = text[start:end]
                # Content-bound identity prevents a changed source/chunk size
                # from silently reinterpreting a previously returned handle.
                identity = sha256(encode({"source_id": source_ids[event["seq"]],
                    "start": start, "end": end, "text": value}).encode()).hexdigest()
                ref = f"{event['id']}:{start}:{end}:{identity}"
                catalog[ref] = (event["seq"], start, end, value)
                blocks.append({"ref": ref, "text": value})
        events.append({**{k: v for k, v in event.items() if k != "text"},
                       "public_text_available": text is not None,
                       "public_text_characters": len(text) if text is not None else None,
                       "spans": blocks})
    return {**offered, "events": events}, catalog


def span_material(material, *, max_chars=1024, boundary_policy="fixed"):
    return _catalog(material, max_chars, boundary_policy)[0]


def compile_spans(material, draft, *, max_chars=1024, boundary_policy="fixed"):
    require(isinstance(draft, dict) and set(draft) <= {
        "source_ids", "understanding_refs", "new_understandings", "clues", "span_refs"},
        "span_selection_shape_invalid")
    selected = compile_selection(material, {k: v for k, v in draft.items() if k != "span_refs"})
    _, catalog = _catalog(material, max_chars, boundary_policy)
    refs = string_list(draft.get("span_refs", []))
    require(all(ref in catalog for ref in refs), "span_reference_missing_or_changed")
    sources = {e["seq"]: e["id"] for e in material["events"]}
    excerpts = []
    for ref in dict.fromkeys(refs):
        seq, start, end, value = catalog[ref]
        excerpts.append(Excerpt(ref, sources[seq], (), start, end,
                                sha256(value.encode()).hexdigest(), basis="public_text"))
    return replace(selected, excerpts=tuple(excerpts))


class SpanSelectionGenerator:
    """Opt-in model frontend; its offered-material byte cap includes span metadata."""
    def __init__(self, generate_draft, *, max_chars=1024, max_material_bytes=262144, boundary_policy="fixed"):
        self.generate_draft = generate_draft
        self.max_chars, self.max_material_bytes = max_chars, max_material_bytes
        self.boundary_policy = boundary_policy

    def __call__(self, material):
        offered = span_material(material, max_chars=self.max_chars, boundary_policy=self.boundary_policy)
        if len(encode(offered).encode()) > self.max_material_bytes:
            error = WSCError("span_material_byte_budget_exhausted")
            # This explicit adapter has not invoked its model callable.
            error.usage = Usage(0, 0, 0)
            raise error
        result = self.generate_draft(offered)
        require(isinstance(result, SelectionDraft) and isinstance(result.usage, Usage),
                "span_generation_result_invalid")
        try:
            selected = compile_spans(material, result.selection, max_chars=self.max_chars,
                                     boundary_policy=self.boundary_policy)
        except WSCError as exc:
            exc.usage = result.usage
            raise
        return Generated(selected, result.usage)
