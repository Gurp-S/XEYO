"""Replace a large payload with a skeleton: key paths, types and lengths."""
from .registry import Action, encode, already_denoised, is_control, pointer_for, replace, row_size, size

ID = "outline_json"
REVERSIBLE = "exact"

MIN_BYTES = 2048
MAX_KEYS = 24


def skeleton(value, depth=0):
    if isinstance(value, dict):
        keys = list(value)[:MAX_KEYS]
        outlined = {key: skeleton(value[key], depth + 1) for key in keys}
        if len(value) > MAX_KEYS:
            outlined["..."] = {"type": "omitted_keys", "count": len(value) - MAX_KEYS}
        return outlined
    if isinstance(value, list):
        return {"type": "list", "length": len(value),
                "first": skeleton(value[0], depth + 1) if value else None}
    if isinstance(value, str):
        if len(value) <= 32:
            return value
        return {"type": "str", "length": len(value)}
    return value


def apply(rows):
    result, actions = [], []
    for row in rows:
        payload = row.get("payload")
        if is_control(row) or already_denoised(row) or not isinstance(payload, dict) or size(payload) < MIN_BYTES:
            result.append(row)
            continue
        before = row_size(row)
        updated = replace(row, payload={"denoise": {"rule": ID, "outline": skeleton(payload)}})
        if row_size(updated) >= before:
            result.append(row)
            continue
        actions.append(Action(ID, row["id"], before, row_size(updated), pointer_for(row, ID)))
        result.append(updated)
    return result, actions
