"""Isolated source-layout persistence and head-seal compatibility prototype.

No production imports of this module. The existing working/head-store serializers
remain authoritative; source layout is machine metadata, never model-visible.
"""
from evals.wsc_append_state import AppendStateStore
from memory.wsc_source_layout import LEGACY, APPEND, validate


def source_messages(store, layout):
    validate(layout)
    if layout == LEGACY:
        return store.as_api_messages()
    # The API/export view stays unchanged. Compression uses its own source view.
    return AppendStateStore(list(store.items)).as_api_messages()


\n