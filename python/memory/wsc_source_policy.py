"""One source policy for startup, automatic and manual compression.

An explicit snapshot override is only a transient experiment control. Ordinary
sessions follow the registered switch; no model-visible text is introduced.
"""
from memory.wsc_source_layout import LEGACY, reset_compression

SUPPORTED_CARRIERS = frozenset(("notice_fragment", "system_channel", "env_channel", "skip"))


def enabled(working=None):
    override = getattr(working, "compression_source_transition_enabled", None)
    if override is not None:
        return bool(override)
    from memory.memory_switches import env_flag
    return env_flag("XEYO_WSC_APPEND_SOURCE") and env_flag("XEYO_WSC")


def hydrate_source(session_id):
    from memory.working import hydrate
    return hydrate(session_id, source_layout=None if enabled() else LEGACY)


def configure_source(working, *, cwd, carrier):
    """Return eligibility; unsupported/disabled paths cannot reuse append cursors."""
    eligible = enabled(working) and carrier in SUPPORTED_CARRIERS
    if not eligible and getattr(working, "compression_source_layout", LEGACY) != LEGACY:
        from memory import wsc_projection as wp
        reset_compression(working)
        working.compression_source_layout = LEGACY
        wp._STATE.pop(wp._state_key(working.session_id, cwd), None)
    return eligible
