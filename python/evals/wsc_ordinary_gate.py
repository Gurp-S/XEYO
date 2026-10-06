"""Single-process shadow: price ordinary source rows without changing projection.

Only the proxy's three read-only calculations are replaced during one native
APPEND extension. This is not a production hook or actual emitted-cost meter.
"""
from contextlib import contextmanager


@contextmanager
def ordinary_gate(working, enabled):
    from memory import runtime
    from memory.wsc_source_layout import APPEND

    if not enabled or getattr(working, "compression_source_layout", None) != APPEND:
        yield
        return
    names = ("_region_tokens", "_region_chars", "c2_summary_extension")
    originals = {name: getattr(runtime, name) for name in names}
    def wrap(function):
        def calculate(rows, *args, **kwargs):
            return function([row for row in rows if not row.get("note_key")], *args, **kwargs)
        return calculate
    try:
        for name, function in originals.items():
            setattr(runtime, name, wrap(function))
        yield
    finally:
        for name, function in originals.items():
            setattr(runtime, name, function)
