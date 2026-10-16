"""Descriptions containing discovery data cannot be replaced by generic summaries."""
from copy import deepcopy


def preserve_discovery(schema: dict) -> dict | None:
    if schema.get("name") == "Skill":
        return deepcopy(schema)
    return None
