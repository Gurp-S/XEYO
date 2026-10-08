"""Continue a saved head without overwriting its untracked cold layout."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


_GENERATION = re.compile(r"^(.*?)(?:\.g-[a-f0-9]{16}-[0-9]+|\.v-sha256-[a-f0-9]{64})+$")


def prior_generation(current: str, candidate: str) -> bool:
    """Only the same native session file family, never the whole cold directory."""
    here, other = Path(current), Path(candidate)
    match = _GENERATION.fullmatch(here.stem)
    if not match or here.parent != other.parent or here.suffix != other.suffix:
        return False
    prior = _GENERATION.fullmatch(other.stem)
    return match.group(1) == (prior.group(1) if prior else other.stem)


def resume_inputs(cached, path, *, mode: str, level: str):
    """Known layouts append in place; lost layouts start a new generation.

    A saved head is already an immutable emission. Its whole text can be one
    journal row until the next rebase, without guessing its internal sections.
    Existing Read references keep their original file and physical ranges.
    """
    previous = cached.prev if cached is not None else None
    cold = cached.cold if cached is not None else None
    path = Path(path)
    if cold is not None:
        return previous, cold, path
    if cached is not None and cached.head and previous is None:
        from synaptic.assemble import AssemblyState

        header, separator, body = cached.head.partition(" ")
        if separator:
            previous = AssemblyState(
                mode=mode, level=level, full_text=cached.head,
                journal=((header, body),),
                lifecycle=dict(getattr(cached, "lifecycle", {}) or {}),
            )
    if path.exists():
        # No layout metadata means even an equal history is insufficient to
        # overwrite this file: previous fold order determines the line layout.
        digest = hashlib.sha256(
            str(getattr(cached, "head", "")).encode("utf-8")
        ).hexdigest()[:16]
        generation = _GENERATION.fullmatch(path.stem)
        stem = generation.group(1) if generation else path.stem
        base = path.with_name(f"{stem}.g-{digest}")
        number = 0
        while True:
            candidate = base.with_name(f"{base.name}-{number}{path.suffix}")
            if not candidate.exists():
                path = candidate
                break
            number += 1
    return previous, cold, path
