"""Shadow source transition: preserve history, discard ambiguous coordinates.

Existing filtered-source numeric cursors do not identify raw-history boundaries.
This transition deliberately forces one fresh fold; no old cursor is reinterpreted.
Production still needs a durable source-layout contract and coordinated entrypoints.
"""
from evals.wsc_append_state import AppendStateStore
from memory.wsc_source_transition import invalid_frozen_source, invalid_persisted_source


def transition_to_append(lifecycle, working):
    if lifecycle.storage == "append":
        return False
    lifecycle.store = AppendStateStore(list(lifecycle.store.items))
    lifecycle.storage = "append"
    rebase_compression(working)
    return True


def rebase_compression(working):
    # Only compression state resets. Current state, pending emitted notes, ordinary
    # messages, mode, tools and user state remain intact. Physical cold files remain.
    from memory.wsc_source_layout import reset_compression
    reset_compression(working)
