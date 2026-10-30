"""Replace a byte-identical repeat with a pointer to the first occurrence."""
from .registry import (Action, content_sha256, already_denoised, is_control, pointer_for, replace,
                       row_size)

ID = "dedupe_identical"
REVERSIBLE = "pointer"


def apply(rows):
    seen: dict[str, str] = {}
    result, actions = [], []
    for row in rows:
        if is_control(row) or already_denoised(row):
            result.append(row)
            continue
        key = content_sha256(row)
        first = seen.get(key)
        if first is None:
            seen[key] = row["id"]
            result.append(row)
            continue
        before = row_size(row)
        updated = replace(row, payload={"denoise": {"rule": ID, "same_as": first}},
                          text=f"[same content as {first}]")
        if row_size(updated) >= before:
            # A pointer that is longer than the content is not a saving.
            result.append(row)
            continue
        actions.append(Action(ID, row["id"], before, row_size(updated),
                              {"rule": ID, "same_as": first, "content_sha256": key,
                               "recover": "source_read"}))
        result.append(updated)
    return result, actions
