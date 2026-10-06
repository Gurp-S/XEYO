"""Machine identity for compression source coordinates; no model-visible text."""
import hashlib

LEGACY = "latest-notes-v1"
APPEND = "append-notes-v1"


def validate(layout):
    if layout not in (LEGACY, APPEND):
        raise ValueError("unknown compression source layout")
    return layout


def bind_seal(raw, layout):
    validate(layout)
    return raw if layout == LEGACY else hashlib.sha256((layout + "\0" + raw).encode()).hexdigest()


def reset_compression(snapshot):
    """Discard incompatible source coordinates; preserve user state and history."""
    snapshot.compact_cursor = 0
    snapshot.c1_frozen_until = 0
    snapshot.c2_summary_text = ""
    snapshot.compact_checkpoint = None
    snapshot.proj_cache = None
    snapshot.c2_gap_shots = 0
    snapshot.turns_since_c2 = 0
    snapshot._pending_c2_summary = None


def restore_source(snapshot, stored_layout, expected_layout):
    validate(expected_layout)
    compatible = stored_layout == expected_layout
    if not compatible:
        reset_compression(snapshot)
    snapshot.compression_source_layout = expected_layout
    snapshot.compression_source_rebuilt = not compatible
    return snapshot
