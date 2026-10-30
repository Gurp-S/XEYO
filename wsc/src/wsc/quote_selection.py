"""Opt-in model selection frontend: exact quotes become source-bound excerpts.

The caller supplies the model and selection policy. This module does not rank
sources, scan current files, infer applicability, or retry a model response.
"""
from dataclasses import dataclass, field, replace
from hashlib import sha256

from .contracts import Generated, Usage, WSCError, require
from .excerpts import Excerpt
from .generation import selection_from_json, string_list


@dataclass(frozen=True)
class SelectionDraft:
    selection: dict
    usage: Usage = field(default_factory=Usage)


def _sources(material):
    sources = {}
    identities = set()
    for event in material["events"]:
        seq, identity = event["seq"], event["id"]
        require(type(seq) is int and seq > 0 and isinstance(identity, str)
                and identity and identity not in identities, "quote_material_identity_invalid")
        alias = f"s{seq}"
        require(alias not in sources and event["kind"] != "opaque", "quote_material_identity_invalid")
        sources[alias] = event
        identities.add(identity)
    return sources


def selection_material(material):
    """Short source handles retain event order, observation times and revisions."""
    sources = _sources(material)
    aliases = {event["id"]: alias for alias, event in sources.items()}
    extra = {}
    if "selection_facts" in material:
        from .selection_facts import alias_sources
        extra["selection_facts"] = alias_sources(material["selection_facts"], aliases)
    return {**material,
            **extra,
            "events": [{**event, "id": alias} for alias, event in sources.items()],
            "understandings": [{**record, "sources": [aliases.get(key, key) for key in record["sources"]]}
                               for record in material["understandings"]]}


def compile_selection(material, draft):
    """Compile only caller-selected, unique, byte-exact public-text quotations.

The compiler input is the same immutable material supplied to the generator.
WSC.prepare separately revalidates the live snapshot and source permissions.
"""
    require(isinstance(draft, dict) and set(draft) <= {
        "source_ids", "understanding_refs", "new_understandings", "clues", "quotes"},
        "quote_selection_shape_invalid")
    sources = _sources(material)

    def expand(keys):
        keys = string_list(keys)
        require(all(key in sources for key in keys), "quote_source_missing")
        return [sources[key]["id"] for key in keys]

    value = {key: val for key, val in draft.items() if key != "quotes"}
    value["source_ids"] = expand(value.get("source_ids", []))
    for field_name in ("new_understandings", "clues"):
        records = value.get(field_name, [])
        require(isinstance(records, list) and all(isinstance(r, dict) for r in records),
                "quote_record_list_invalid")
        value[field_name] = [{**record, "sources": expand(record.get("sources", []))}
                             for record in records]
    selected = selection_from_json(value)
    quotes = draft.get("quotes", [])
    require(isinstance(quotes, list), "quote_list_invalid")
    excerpts, keys = [], set()
    for quote in quotes:
        require(isinstance(quote, dict) and set(quote) == {"key", "source_id", "text"},
                "quote_shape_invalid")
        key, alias, text = quote["key"], quote["source_id"], quote["text"]
        require(isinstance(key, str) and key.strip() and key not in keys, "quote_key_invalid_or_duplicate")
        keys.add(key)
        expand([alias])
        source = sources[alias]
        require(isinstance(text, str) and bool(text), "quote_text_empty")
        public = source["text"]
        require(isinstance(public, str), "quote_public_text_unavailable")
        start = public.find(text)
        require(start >= 0, "quote_text_missing")
        # Overlapping matches count too; no first-match or similarity fallback.
        require(public.find(text, start + 1) < 0, "quote_text_ambiguous")
        excerpts.append(Excerpt(key, source["id"], (), start, start + len(text),
                                sha256(text.encode("utf-8")).hexdigest(), basis="public_text"))
    return replace(selected, excerpts=tuple(excerpts))


class QuoteSelectionGenerator:
    """Adapts an explicitly supplied model callable to WSC.generate.

The callable receives selection_material and returns SelectionDraft. Semantic
policy and transport remain with the caller; known usage survives compilation
failure. No model call occurs when constructing this adapter.
"""
    def __init__(self, generate_draft):
        self.generate_draft = generate_draft

    def __call__(self, material):
        result = self.generate_draft(selection_material(material))
        require(isinstance(result, SelectionDraft) and isinstance(result.usage, Usage),
                "quote_generation_result_invalid")
        try:
            selection = compile_selection(material, result.selection)
        except WSCError as exc:
            exc.usage = result.usage
            raise
        return Generated(selection, result.usage)
