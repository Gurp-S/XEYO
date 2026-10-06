"""Compare active TODO facts without treating compact labels as identities."""

PENDING = frozenset({"pending", "in_progress", "in-progress", "todo", "open", "not_started"})


def summarize(items):
    """Keep display multiplicity and count independently of truncated labels."""
    if isinstance(items, str):
        return ((items.strip()[:180],) if items.strip() else ()), None
    groups = {}
    count = 0
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        if status not in PENDING:
            continue
        count += 1
        body = str(item.get("content") or item.get("text") or item.get("subject") or "").strip()
        if body:
            label = f"[{status}] {body[:180]}"
            groups[label] = groups.get(label, 0) + 1
    labels = tuple(label if n == 1 else f"{label}（×{n}）" for label, n in groups.items())
    return labels, count


def active_fields(items):
    """Only complete, ordered active records can back observed state.

    Normalize the tool's active_form alias and absent output default. Unknown
    fields and original string bytes remain part of the equality check.
    """
    if not isinstance(items, list):
        return None
    records = []
    known = {"id", "content", "status", "activeForm", "active_form", "output"}
    for item in items:
        if not isinstance(item, dict):
            return None
        status = item.get("status")
        if status not in ("pending", "in_progress"):
            if status == "completed":
                continue
            return None
        uid, content = item.get("id"), item.get("content")
        active = item.get("activeForm", item.get("active_form"))
        output = item.get("output", "")
        if not all(isinstance(v, str) and v.strip() for v in (uid, content, active)) or not isinstance(output, str):
            return None
        record = {key: value for key, value in item.items() if key not in known}
        record.update(id=uid, content=content, status=status, activeForm=active, output=output)
        records.append(record)
    return records


def input_backs_state(inputs, observed):
    left, right = active_fields(inputs), active_fields(observed)
    return left is not None and right is not None and left == right
