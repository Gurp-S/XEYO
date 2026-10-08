"""Model-owned history stays unfolded until an explicit/capacity fold.

The execution layer already owns per-tool output budgets and raw spill.
A history projection must not silently shorten that committed result again
just because it is 8192 characters old/large. Existing frozen regions retain
their established representation; this never unarchives historical heads.
"""
from memory.wsc_timing import enabled


def preserve(*, frozen: bool) -> bool:
    return enabled() and not frozen
