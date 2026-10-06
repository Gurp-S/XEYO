"""Deterministic state-injection replay; archived snapshots are a state oracle.

No model calls. This is a counterfactual lifecycle scenario, not reconstruction
of historically missing system/tools snapshots or a provider usage meter.
"""
from __future__ import annotations

from dataclasses import replace

from session.hydrate import message_from_row
from session.message_store import MessageStore
from session.state_projection import current_context_items
from evals.wsc_state_reuse import StateReuseStore


class StateLifecycle:
    def __init__(self, *, reuse_equal_state: bool, persist: str, dedup: str = "ledger", storage: str = "history", native_working=None):
        self.native_working = native_working
        self.store = StateReuseStore(reuse_equal_state=True) if reuse_equal_state else MessageStore()
        if storage == "append" and native_working is None:
            from evals.wsc_append_state import AppendStateStore
            self.store = AppendStateStore()
        self.persist = persist
        self.dedup = dedup
        self.storage = storage
        self.detached_keys = set()
        self.ledger = {}
        self.end = 0
        self.pending = []
        self.current = {}
        self.shots = 0
        self.injected = 0
        self.stale_visible = 0

    def prepare(self, raw: list[dict]) -> list[dict]:
        notes = [m for row in raw if row.get("note_key") and (m := message_from_row(row)) is not None]
        current = {m.note_key: m for m in current_context_items(notes, include_system_notes=True)}
        if self.storage == "changing":
            changed = {key for key, item in current.items() if key in self.current
                       and (item.role != self.current[key].role or item.content != self.current[key].content)}
            changed.update(self.current.keys() - current.keys())
            newly_detached = changed - self.detached_keys
            self.detached_keys.update(changed)
            if newly_detached:
                self.store.replace([m for m in self.store.items if m.note_key not in newly_detached])
        for key in self.current.keys() - current.keys():
            self.store.retract_note(key)
            self.ledger.pop(key, None)
        self.current = current
        new = [m for row in raw[self.end:] if not row.get("note_key") and (m := message_from_row(row)) is not None]
        # Pending snapshots really were emitted in the preceding request. They
        # precede its generated response in early mode; late matches persist_pending.
        pending = ([] if self.storage == "detached" else
                   [m for m in self.pending if m.note_key not in self.detached_keys])
        early = self.persist == "early"
        if self.persist == "native-early":
            from memory.wsc_source_layout import APPEND
            early = self.native_working is not None and self.native_working.compression_source_layout == APPEND
        groups = (pending, new) if early else (new, pending)
        for group in groups:
            for item in group:
                if item.note_key and item.note_key not in current:
                    item = replace(item, note_retracted=True)
                self.store.append(item)
                if item.note_key and not item.note_retracted:
                    self.ledger[item.note_key] = item.note_fp
        self.pending = []
        self.end = len(raw)
        result = self.store.as_api_messages()
        original = MessageStore([m for row in raw if not row.get("note_key")
                                 and (m := message_from_row(row)) is not None]).as_api_messages()
        if [row for row in result if not row.get("note_key")] != original:
            raise AssertionError("state lifecycle changed ordinary history")
        if self.native_working is not None:
            from session.compression_source import compression_messages
            return compression_messages(self.store, self.native_working)
        return result

    def preview(self, out: list[dict]) -> list[dict]:
        return self._inject(out, commit=False)

    def finish(self, out: list[dict], *, fold: bool = False) -> list[dict]:
        result = self._inject(out, commit=True)
        # query_loop invalidates the ledger after assembling a folded request.
        if fold:
            self.ledger.clear()
        return result

    def _inject(self, out: list[dict], *, commit: bool) -> list[dict]:
        if self.storage == "append":
            current = {key: {"role": item.role, "content": item.content, "note_fp": item.note_fp}
                       for key, item in self.current.items()}
            if self.native_working is not None:
                from prompt.state_emission import select_rendered_state
                out = select_rendered_state(out, out, current, "system_channel")
            else:
                from evals.wsc_append_state import select_note_rows
                out = select_note_rows(out, current)
        # Production observes visibility before this round's new injection.
        if commit:
            self.store.note_fingerprints(projected=out)
        actual = {row["note_key"]: row for row in out if row.get("note_key")}
        result = list(out)
        for key, item in self.current.items():
            row = actual.get(key)
            same = row is not None and row.get("role") == item.role and row.get("content") == item.content and row.get("note_fp", "") == item.note_fp
            if self.dedup == "ledger":
                same = same and self.ledger.get(key) == item.note_fp
            if same:
                continue
            if commit:
                self.stale_visible += int(row is not None and row.get("content") != item.content)
            result.append({"role": item.role, "content": item.content,
                           "note_key": key, "note_fp": item.note_fp})
            if commit:
                self.pending.append(replace(item, id=f"state-replay-{self.shots}-{key}"))
                self.injected += 1
        latest = {row["note_key"]: row for row in result if row.get("note_key")}
        for key, item in self.current.items():
            if latest[key].get("content") != item.content or latest[key].get("role") != item.role:
                raise AssertionError("current state not delivered intact")
        if commit:
            self.shots += 1
        return result
