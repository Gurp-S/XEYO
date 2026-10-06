"""Observe first differing normalized row; classification is not cost attribution."""
import json


def identity(row):
    return row.get("role"), json.dumps(row.get("content"), ensure_ascii=False, sort_keys=True)


def state_identities(projection):
    return {identity(row) for row in projection if row.get("note_key")}


def first_difference(previous, current, previous_states=(), current_states=()):
    if previous is None:
        return {"kind": "initial_request", "equal_rows": 0}
    i = 0
    while i < min(len(previous), len(current)) and previous[i] == current[i]:
        i += 1
    if i == len(previous) and len(current) >= len(previous):
        return {"kind": "append_only" if len(current) > len(previous) else "unchanged", "equal_rows": i}
    old = previous[i] if i < len(previous) else None
    new = current[i] if i < len(current) else None
    states = set(previous_states) | set(current_states)
    if (old is not None and identity(old) in states) or (new is not None and identity(new) in states):
        kind = "state_row_changed_or_moved"
    elif i == 0:
        kind = "first_row_changed"
    elif new is None:
        kind = "suffix_removed"
    else:
        kind = "ordinary_tail_difference"
    moved_index = next((j for j, row in enumerate(current) if row == old), None) if old is not None else None
    return dict(kind=kind, equal_rows=i, previous_rows=len(previous), current_rows=len(current),
                previous_role=old.get("role") if old else None,
                current_role=new.get("role") if new else None,
                previous_row_still_present=moved_index is not None, old_row_new_index=moved_index)
