"""Read-only compression inputs separate from provider/API history selection.

The native API cache owns revision and pairing cleanup. Append sources retain
all note versions for stable coordinates. Callers use store mutation methods
and never mutate the returned rows.
"""
from weakref import WeakKeyDictionary

from memory.wsc_source_layout import LEGACY, validate


class SourceReader:
    def __init__(self):
        self._cache = WeakKeyDictionary()

    def read(self, store, layout):
        validate(layout)
        api = store.as_api_messages()
        if layout == LEGACY:
            return api
        cached = self._cache.get(store)
        if cached is not None and cached[0] is api:
            return cached[1]
        rows = []
        for item in store.items:
            row = {"role": item.role, "content": item.content}
            if item.role == "tool":
                if item.tool_call_id:
                    row["tool_call_id"] = item.tool_call_id
                if item.name:
                    row["name"] = item.name
            elif item.note_key:
                row.update(note_key=item.note_key, note_fp=item.note_fp)
            rows.append(row)
        self._cache[store] = (api, rows)
        return rows


_reader = SourceReader()


def compression_messages(store, working):
    return _reader.read(store, getattr(working, "compression_source_layout", LEGACY))
