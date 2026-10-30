"""Opt-in facts about selection consequences, derived from the real snapshot.

These describe representation and storage, not semantic value or a task plan.
Serialized view bytes are not model tokens, rendered bytes or host capacity.
"""
from .contracts import encode
from .view_budget import mandatory_sources, minimum_view_bytes


def describe(prefix, max_view_bytes):
    mandatory = {row["id"] for row in mandatory_sources(prefix)}
    return {
        "schema": "wsc.selection_facts/1",
        "serialized_view_limit_bytes": max_view_bytes,
        "mandatory_empty_view_bytes": minimum_view_bytes(prefix),
        "source_records": {row["id"]: {
            "automatically_retained": row["id"] in mandatory,
            "serialized_record_bytes": len(encode(row).encode("utf-8")),
            "public_text_utf8_bytes": len((row["text"] or "").encode("utf-8")),
        } for row in prefix if row["kind"] != "opaque"},
        "selection_effects": {
            "source_ids": "Complete source records in the prepared view; repeated identities occur once.",
            "quotes": "Selected exact public-text slices and their source bindings in the prepared view.",
            "understandings_and_clues": "Model-authored content and provenance; source links do not inline the linked source records.",
            "omitted_sources": "Remain in the WSC source store; selection does not delete them.",
            "successful_stage": "Exports all sources observed at staging, including unselected sources, subject to authorization and export success.",
            "external_access": "Export is not host installation or proof of later access; runtime permissions and host delivery remain separate.",
        },
        "measurement_scope": "Prepared-view JSON in UTF-8, including stored source payloads and public text; not model tokens or adapter-rendered request bytes. Array separators and model records add bytes.",
    }


def alias_sources(facts, aliases):
    return {**facts, "source_records": {aliases[key]: value
                                        for key, value in facts["source_records"].items()}}
