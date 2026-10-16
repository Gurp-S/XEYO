"""Bind media to its result row until pairing validation has completed."""

_MEDIA = "_xeyo_tool_media"


def bind_media(rows: list[dict], images: list[dict], call_id: str) -> None:
    if not images or not rows:
        return
    matches = [r for r in rows if r.get("tool_call_id") == call_id] if call_id else rows
    if len(matches) == 1:
        matches[0][_MEDIA] = images


def finish_media(rows: list[dict]) -> list[dict]:
    from model.tool_media import append_tool_media
    out: list[dict] = []
    pending: list[dict] = []
    for row in rows:
        if row.get("role") != "tool":
            append_tool_media(out, pending)
        if _MEDIA in row:
            pending.extend(row[_MEDIA])
            row = {key: value for key, value in row.items() if key != _MEDIA}
        out.append(row)
    append_tool_media(out, pending)
    return out
