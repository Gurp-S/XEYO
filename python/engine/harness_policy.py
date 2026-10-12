"""Rollout domains. Explicit 0 keeps the previous implementation for paired probes."""
import os

DEFAULTS = {
    "XEYO_HARNESS_WRITES": True,
    "XEYO_HARNESS_FACTS": True,
    "XEYO_HARNESS_HEALTH": True,
    "XEYO_HARNESS_QUERIES": True,
    "XEYO_HARNESS_RESOURCES": False,
    "XEYO_HARNESS_OUTPUT_BYTES": True,
}


def enabled(name):
    raw = os.environ.get(name, "").strip().lower()
    return DEFAULTS[name] if not raw else raw not in {"0", "false", "off", "no"}
