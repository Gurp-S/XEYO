"""Stable product contract shared by pure projection and production adapters."""


def enabled() -> bool:
    # User-selected model timing and task continuity cannot be disabled by
    # legacy experiment environment values.
    return True
