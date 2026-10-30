"""Shared JSON selection decoding; no execution or generator dependency."""
from dataclasses import fields
from .contracts import Selection, Understanding, require
from .excerpts import Excerpt


def string_list(value):
    require(isinstance(value, (list, tuple)) and all(isinstance(x, str) and x for x in value),
            "source_reference_list_invalid")
    return tuple(value)


def selection_from_json(value):
    require(isinstance(value, dict) and set(value) <= {f.name for f in fields(Selection)},
            "selection_shape_invalid")
    records = value.get("new_understandings", [])
    require(isinstance(records, list), "understanding_list_invalid")
    parsed = []
    for record in records:
        require(isinstance(record, dict) and set(record) <= {f.name for f in fields(Understanding)}
                and {"text", "kind"} <= set(record), "understanding_shape_invalid")
        record = {**record, "sources": string_list(record.get("sources", []))}
        parsed.append(Understanding(**record))
    clues = value.get("clues", [])
    require(isinstance(clues, list), "clue_list_invalid")
    excerpts = value.get("excerpts", [])
    require(isinstance(excerpts, list), "excerpt_list_invalid")
    for item in excerpts:
        require(isinstance(item, dict) and set(item) <= {f.name for f in fields(Excerpt)} and
                {"key", "source_id", "path", "start", "end", "text_sha256"} <= item.keys(),
                "excerpt_shape_invalid")
    return Selection(source_ids=string_list(value.get("source_ids", [])),
                     understanding_refs=string_list(value.get("understanding_refs", [])),
                     new_understandings=tuple(parsed), clues=tuple(clues),
                     excerpts=tuple(Excerpt(**item) for item in excerpts))


