"""Structural guarantees for a denoise pass.

These checks do not claim the model will not need the removed detail. They claim
something narrower and checkable: nothing was lost silently. Every changed row
keeps its identity, every control row is byte-identical, every removed byte has
a pointer whose hash matches the original, and every changed row says that it
was changed.
"""
from hashlib import sha256

from ..contracts import WSCError, encode, require

IDENTITY = ("id", "kind", "call_id", "role", "control")

MARKERS = ("[same content as", "[superseded by", "chars omitted", "diff body omitted",
           "[denoise:", "  [x")


def content_digest(row: dict) -> str:
    return sha256(encode({"payload": row.get("payload"), "text": row.get("text")}).encode("utf-8")).hexdigest()


def is_marked(row: dict) -> bool:
    """A changed row must announce that it was changed."""
    payload = row.get("payload")
    if isinstance(payload, dict) and "denoise" in payload:
        return True
    text = row.get("text")
    return isinstance(text, str) and any(marker in text for marker in MARKERS)


def verify(before: list[dict], after: list[dict], actions) -> dict:
    """Raise WSCError on any structural violation; return a summary otherwise."""
    require(len(before) == len(after), "denoise_row_count_changed")
    by_id = {row["id"]: row for row in before}
    changed = {action.source_id: action for action in actions}
    for old, new in zip(before, after):
        require(old["id"] == new["id"], "denoise_row_order_changed")
        for key in IDENTITY:
            require(old.get(key) == new.get(key), f"denoise_identity_changed:{key}")
        if old.get("control") is True or old.get("role") in {"system", "developer", "user"}:
            require(old == new, "denoise_control_row_changed")
        touched = old != new
        require(touched == (new["id"] in changed), "denoise_action_row_mismatch")
        if touched:
            require(is_marked(new), "denoise_change_without_marker")
    for action in actions:
        original = by_id.get(action.source_id)
        require(original is not None, "denoise_action_source_missing")
        require(action.pointer is not None, "denoise_action_pointer_missing")
        require(action.pointer.get("content_sha256") == content_digest(original),
                "denoise_pointer_hash_mismatch")
    return {"rows": len(before), "changed": len(actions),
            "control_unchanged": True, "pointers": len(actions),
            "marked": sum(1 for row in after if is_marked(row))}


def recover(actions, before: list[dict]) -> dict[str, dict]:
    """Original rows keyed by source id, checked against the recorded hashes."""
    by_id = {row["id"]: row for row in before}
    restored = {}
    for action in actions:
        original = by_id.get(action.source_id)
        if original is None:
            raise WSCError("denoise_action_source_missing")
        if action.pointer and action.pointer.get("content_sha256") != content_digest(original):
            raise WSCError("denoise_pointer_hash_mismatch")
        restored[action.source_id] = original
    return restored
