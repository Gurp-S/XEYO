"""Shadow only: retain the first position of an uninterrupted identical state run.

Never compares fingerprints alone. Retraction, role change, or any content
change starts a new run. Production selection remains unchanged: reinjection
after a fold may be required even when the value is identical.
"""
from __future__ import annotations

from msgtypes.message import Message
from session.state_projection import current_context_items
from evals.wsc_state_reuse import reuse_visible_state


def equal_state_items(items: list[Message], *, include_system_notes: bool) -> list[Message]:
    chosen: dict[str, Message] = {}
    for item in items:
        if not item.note_key:
            continue
        key = item.note_key
        if item.note_retracted or (item.role == "system" and not include_system_notes):
            chosen.pop(key, None)
            continue
        old = chosen.get(key)
        if old is None or old.role != item.role or old.content != item.content:
            chosen[key] = item
    return [item for item in items if not item.note_key or chosen.get(item.note_key) is item]


class VisibleEqualState:
    """Only reuse an equal version that was actually in the preceding raw tail.

    No assumption that a note survived compression. The replay wires record_tail
    to the actual emission boundary, not the requested compact cursor.
    """

    def __init__(self) -> None:
        self.ordered: list[Message] = []
        self.visible: set[str] = set()
        self.checked = 0
        self.reused = 0

    def select(self, items: list[Message], *, include_system_notes: bool) -> list[Message]:
        selected = current_context_items(items, include_system_notes=include_system_notes)
        self.checked += 1
        self.ordered = reuse_visible_state(items, selected, self.ordered, self.visible)
        latest_ids = {m.note_key: m.id for m in selected if m.note_key}
        self.reused += sum(m.id != latest_ids[m.note_key] for m in self.ordered if m.note_key)
        def facts(rows):
            return {m.note_key: (m.role, m.content, m.note_fp, m.note_kind) for m in rows if m.note_key}
        if facts(self.ordered) != facts(selected):
            raise AssertionError("state reuse changed authoritative state")
        if [m for m in self.ordered if not m.note_key] != [m for m in selected if not m.note_key]:
            raise AssertionError("state reuse changed non-state history")
        return self.ordered

    def record_tail(self, base: int) -> None:
        self.visible = {m.id for m in self.ordered[max(0, base):] if m.note_key}
