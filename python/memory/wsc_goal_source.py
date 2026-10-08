"""Read an explicitly bound goal; never derive or mutate one during projection."""
from __future__ import annotations


def snapshot(cwd, session):
    from synaptic.contracts import enabled
    if not enabled() or not cwd or not session:
        return None
    from engine.goal_state import GoalStore
    import json
    store = GoalStore(cwd)
    bindings = [path for path in store._binding_path_candidates(session) if path.exists()]
    if not bindings:
        return None
    binding = json.loads(bindings[0].read_text(encoding="utf-8"))
    if not isinstance(binding, dict) or not isinstance(binding.get("goal_id"), str) or not binding["goal_id"]:
        raise ValueError("goal_binding_unavailable")
    goal = store.current(session)
    if goal is None:
        # Unreadable bound state is unknown, never an inferred unbinding event.
        raise ValueError("bound_goal_unavailable")
    return goal.to_dict()
