"""XEYO enterprise rewind primitives.

Rewind is enabled by default. Set ``XEYO_REWIND_ENABLED=0`` to disable.

Full shadow-git tree restore is **off** by default (scoped agent-file restore).
Set ``XEYO_REWIND_FULL_TREE=1`` or pass ``full_tree_restore=true`` on execute to enable.
"""

from __future__ import annotations

import os

_DISABLED = frozenset({"0", "false", "no", "off", "disabled"})
_ENABLED = frozenset({"1", "true", "yes", "on", "enabled"})


def is_rewind_enabled() -> bool:
    """Return whether durable rewind recording is enabled (default: on)."""

    value = os.environ.get("XEYO_REWIND_ENABLED", "1").strip().lower()
    return value not in _DISABLED


def is_rewind_full_tree_enabled() -> bool:
    """Return whether full shadow-git tree restore is allowed (default: off)."""

    value = os.environ.get("XEYO_REWIND_FULL_TREE", "0").strip().lower()
    return value in _ENABLED


__all__ = ["is_rewind_enabled", "is_rewind_full_tree_enabled"]
