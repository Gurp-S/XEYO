"""Keep only the newest observation of a resource; older reads become pointers.

This is the V1/V2 case: an old read of a file that has since changed is worse
than useless, because it still looks like current evidence.
"""
from .registry import Action, already_denoised, is_control, pointer_for, replace, row_size

ID = "dedupe_reads"
REVERSIBLE = "pointer"

PATH_KEYS = ("path", "file_path", "resource")


def resource_of(row) -> str | None:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    for key in PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def apply(rows):
    newest: dict[str, tuple[int, str]] = {}
    for row in rows:
        if is_control(row):
            continue
        path = resource_of(row)
        if path is None:
            continue
        seq = row.get("seq", 0)
        if path not in newest or seq >= newest[path][0]:
            newest[path] = (seq, row["id"])
    result, actions = [], []
    for row in rows:
        path = None if is_control(row) or already_denoised(row) else resource_of(row)
        if path is None or newest[path][1] == row["id"]:
            result.append(row)
            continue
        before = row_size(row)
        updated = replace(row, payload={"denoise": {"rule": ID, "superseded_by": newest[path][1],
                                                    "resource": path}},
                          text=f"[superseded by {newest[path][1]}]")
        if row_size(updated) >= before:
            result.append(row)
            continue
        actions.append(Action(ID, row["id"], before, row_size(updated),
                              {"rule": ID, "resource": path, "superseded_by": newest[path][1],
                               "recover": "source_read"}))
        result.append(updated)
    return result, actions
