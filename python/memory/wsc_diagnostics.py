"""Bounded local failure evidence; never injected into model attention."""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path


def record(stage: str, exc: Exception, *, session: str = "") -> None:
    logging.getLogger(__name__).warning("WSC fallback stage=%s type=%s", stage, type(exc).__name__)
    try:
        root = Path(os.environ.get("XEYO_HOME") or Path.home() / ".xeyo")
        path = root / "wsc_diagnostics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 256_000:
            os.replace(path, path.with_suffix(".previous.jsonl"))
        # No exception message, commands, input contents, or secret paths.
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps({"stage": stage, "session": session,
                                  "exception_type": type(exc).__name__}) + "\n")
    except Exception:
        pass
