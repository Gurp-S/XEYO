"""Read-only source accounting; never changes a boundary or decision."""
from engine.compact import tool_pair_ranges
from memory.runtime import c2_cut_index, _region_tokens


def audit_source(messages, cursor):
    ordinary = [row for row in messages if not row.get("note_key")]
    cut = c2_cut_index(messages, None)
    ordinary_cut = c2_cut_index(ordinary, None)
    folded_ordinary = sum(not row.get("note_key") for row in messages[:cut])
    region = messages[max(0, cursor):cut]
    notes = [row for row in region if row.get("note_key")]
    pairs = tool_pair_ranges(messages)
    return dict(source_rows=len(messages), state_rows=sum(bool(r.get("note_key")) for r in messages),
                source_cut=cut, ordinary_only_cut=ordinary_cut, folded_ordinary=folded_ordinary,
                ordinary_boundary_delta=folded_ordinary-ordinary_cut, has_tool_pairs=bool(pairs),
                state_rows_inside_tool_pairs=sum(bool(row.get("note_key"))
                    for start, end in pairs for row in messages[start:end]),
                raw_extension_tokens=_region_tokens(region),
                raw_extension_state_tokens=_region_tokens(notes),
                raw_tail_tokens=_region_tokens(messages[cut:]),
                raw_tail_state_tokens=_region_tokens([r for r in messages[cut:] if r.get("note_key")]))
