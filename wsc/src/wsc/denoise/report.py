"""Factual summary of what a denoise pass removed."""
from .registry import Action


def summarize(actions: list[Action], rows_before: int, rows_after: int) -> dict:
    per_rule: dict[str, dict] = {}
    for action in actions:
        entry = per_rule.setdefault(action.rule, {"sources": 0, "before_bytes": 0,
                                                 "after_bytes": 0, "pointers": 0})
        entry["sources"] += 1
        entry["before_bytes"] += action.before_bytes
        entry["after_bytes"] += action.after_bytes
        entry["pointers"] += 1 if action.pointer else 0
    for entry in per_rule.values():
        saved = entry["before_bytes"] - entry["after_bytes"]
        entry["saved_bytes"] = saved
        entry["saved_ratio"] = round(saved / entry["before_bytes"], 4) if entry["before_bytes"] else 0.0
    before = sum(entry["before_bytes"] for entry in per_rule.values())
    after = sum(entry["after_bytes"] for entry in per_rule.values())
    return {"rows_before": rows_before, "rows_after": rows_after,
            "touched_sources": len({action.source_id for action in actions}),
            "before_bytes": before, "after_bytes": after,
            "saved_bytes": before - after,
            "saved_ratio": round((before - after) / before, 4) if before else 0.0,
            "recoverable_ratio": round(sum(entry["saved_bytes"] for entry in per_rule.values()
                                           if entry["pointers"]) / (before - after), 4)
            if before - after else 0.0,
            "rules": per_rule}
