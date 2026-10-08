"""Goal and failure facts are independent of their historical carrier nodes."""
from __future__ import annotations
from dataclasses import replace
from synaptic.seeds import extract_constraints, strip_machine_blocks, _substantive
from synaptic.types import KIND_USER
from synaptic.goal_staleness import closes


def project_goals(seeds, graph, region_end, snapshot=None, dropped=()):
    users = [n for n in graph.nodes if n.idx < region_end and n.kind == KIND_USER
             and _substantive(n.text)]
    retired = []
    current = None
    closing_nodes = set()
    from synaptic.goal_staleness import _GOAL_CLOSE_MARKERS
    declarations = [node for node in users if any(marker in node.text for marker in _GOAL_CLOSE_MARKERS)]
    for node in users:
        text = strip_machine_blocks(node.text)
        if node.idx in closing_nodes:
            continue
        by = next((other for other in declarations if other.idx > node.idx and closes(other.text, text)), None)
        if by is not None:
            retired.append((node.idx, by.idx))
            closing_nodes.add(by.idx)
        else:
            current = node
            break
    goal = strip_machine_blocks(current.text) if current else ""
    provenance = {"authority": "derived", "retired": retired,
                  "source_index": current.idx if current else None}
    if snapshot is not None:
        if not isinstance(snapshot, dict) or not snapshot.get("goal_id") or not isinstance(snapshot.get("revision"), int):
            raise ValueError("invalid_goal_snapshot")
        status = str(snapshot.get("status", ""))
        if status not in {"active", "paused", "blocked", "completed", "abandoned"}:
            raise ValueError("invalid_goal_status")
        goal = str(snapshot.get("text") or "") if status in {"active", "paused", "blocked"} else ""
        provenance.update(authority="authoritative", goal_id=snapshot["goal_id"],
                          revision=snapshot["revision"], status=status)
        current = next((n for n in users if strip_machine_blocks(n.text) == goal), None)
        provenance["source_index"] = current.idx if current else None
    # Constraints survive the retirement of the request which carried them.
    constraints = tuple(dict.fromkeys(c for n in users for c in extract_constraints(strip_machine_blocks(n.text))
                                      if c not in dropped))
    # Keep user history for literal recovery; goal source is independently bound.
    return replace(seeds, original_task=goal, goal=goal, constraints=constraints), provenance


def lifecycle_state(seeds, provenance):
    from synaptic.failure_facts import enabled as facts_enabled
    return {"goal": seeds.original_task, "goal_id": provenance.get("goal_id"),
            "status": provenance.get("status"), "revision": provenance.get("revision"),
            "unresolved": list(seeds.unresolved_identities if facts_enabled() else seeds.unresolved_sigs),
            "failure_identity_schema": "invocation-v1" if facts_enabled() else "signature-v1",
            "request_projection": provenance.get("request_projection", False),
            "request_source": provenance.get("request_source", -1)}


def needs_rebase(previous, current):
    old = getattr(previous, "lifecycle", None)
    if previous is None or not previous.full_text:
        return False
    if not old:
        return True
    return (any(old.get(k) != current.get(k) for k in ("goal", "goal_id", "status", "revision", "request_projection", "request_source", "failure_identity_schema"))
            or bool(set(old.get("unresolved", ())) - set(current["unresolved"])))


def bind_goal(pins, provenance):
    index = provenance.get("source_index")
    return tuple(replace(p, nodes=(index,) if index is not None else ()) if p.key == "goal" else p
                 for p in pins)


def filter_file_failures(states, graph, fresh, region_end):
    """File annotations use the same unresolved evidence as the error channel."""
    active = {graph.node(i).error_sig for i in fresh.unresolved_idx
              if i < region_end and graph.node(i) is not None}
    return {path: replace(state, related_errors=tuple(sig for sig in state.related_errors if sig in active))
            for path, state in states.items()}
