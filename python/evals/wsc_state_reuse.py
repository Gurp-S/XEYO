"""Reuse a byte-identical state only while its preceding version is visible.

No historical facts are added. Changed values, retractions, changed note
identity, and state already absorbed by compression always use latest selection.
"""
from __future__ import annotations

from msgtypes.message import Message
from session.message_store import MessageStore


def reuse_visible_state(items: list[Message], selected: list[Message],
                       prior: list[Message], visible: set[str]) -> list[Message]:
    if not visible:
        return selected
    old = {m.note_key: m for m in prior if m.note_key and m.id in visible}
    positions = {m.id: i for i, m in enumerate(items)}
    if len(positions) != len(items):
        return selected  # Ambiguous identity cannot authorize position reuse.
    choices = {}
    for latest in selected:
        if not latest.note_key:
            continue
        key = latest.note_key
        previous = old.get(key)
        choices[key] = latest
        if previous is None or previous.id not in positions:
            continue
        run = [m for m in items[positions[previous.id]:positions[latest.id] + 1] if m.note_key == key]
        if run and all(not m.note_retracted and m.role == latest.role and m.content == latest.content
                       and m.note_fp == latest.note_fp and m.note_kind == latest.note_kind for m in run):
            choices[key] = items[positions[previous.id]]
    chosen_ids = {m.id for m in choices.values()}
    return [m for m in items if not m.note_key or m.id in chosen_ids]


class StateReuseStore(MessageStore):
    """Rejected production candidate retained solely for reproducible replay."""

    def __init__(self, initial=None, *, reuse_equal_state=False):
        super().__init__(initial)
        self.reuse_equal_state = reuse_equal_state
        self.visible_ids = set()

    def as_api_messages(self):
        if self._api_cache is not None:
            return self._api_cache
        prior = self._api_items
        rows = super().as_api_messages()
        if not self.reuse_equal_state:
            return rows
        selected = self._api_items
        chosen = reuse_visible_state(self._items, selected, prior, self.visible_ids)
        if chosen is selected:
            return rows
        by_id = {item.id: row for item, row in zip(selected, rows)}
        notes = {row["note_key"]: row for row in rows if row.get("note_key")}
        self._api_items = chosen
        self._api_cache = [notes[item.note_key] if item.note_key else by_id[item.id] for item in chosen]
        return self._api_cache

    def note_fingerprints(self, *, start=0, projected=None):
        identities = super().note_fingerprints(start=start, projected=projected)
        self.visible_ids = ({item.id for item in self._api_items
                             if (item.note_key, item.note_fp) in identities}
                            if projected is not None else set())
        return identities
