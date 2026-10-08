"""Opt-in request focus; historical requests are recoverable, not inferred goals."""
from __future__ import annotations

import os
from dataclasses import replace

from synaptic.seeds import _ENGINE_INJECTED, extract_constraints, strip_machine_blocks
from synaptic.types import KIND_USER

ENV = "XEYO_WSC_REQUEST_PROJECTION"


def enabled():
    return os.environ.get(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def project_requests(seeds, graph, messages, region_end, snapshot, dropped=()):
    # The API role and structured note metadata identify carriers. Short human
    # follow-ups are accepted; no semantic task-switch or completion inference.
    users = []
    lossless = (os.environ.get("XEYO_WSC_TASK_CONTINUITY", "").strip().lower()
                in {"1", "true", "yes", "on"})
    identities = {}
    for node in graph.nodes:
        msg = messages[node.idx]
        text = node.text if lossless else strip_machine_blocks(node.text, preserve_layout=True)
        if (node.kind != KIND_USER or str(msg.get("role", "")).lower() not in {"user", "human"} or not text
                or any(msg.get(k) for k in ("note_key", "note_kind", "note_retracted"))
                or (not lossless and text.lower().startswith(_ENGINE_INJECTED))):
            continue
        identity = msg.get("id") or msg.get("message_id")
        if identity:
            identity = str(identity)
            if identity in identities:
                if identities[identity] != node.text:
                    raise ValueError("request_identity_conflict")
                continue
            identities[identity] = node.text
        users.append(node)
    latest = users[-1] if users else None
    source = latest.idx if latest is not None and latest.idx < region_end else -1
    regional = [node for node in users if node.idx < region_end]
    constraints = tuple(dict.fromkeys(
        c for node in regional for c in extract_constraints(strip_machine_blocks(node.text))
        if c not in dropped))
    if lossless:
        # Keyword matches cannot establish persistent authority, especially
        # inside historical quotations or pasted third-party proposals.
        constraints = ()
    goal = ""
    provenance = {"authority": "request_projection", "source_index": None,
                  "request_source": source, "request_projection": True}
    if snapshot is not None:
        from synaptic.lifecycle import project_goals
        bound, authoritative = project_goals(seeds, graph, region_end, snapshot, dropped)
        goal = bound.goal
        provenance.update(authoritative)
    # Excluded/duplicate user carriers must not leak their bodies through MAIN.
    carrier_ids = {node.idx for node in graph.nodes if node.kind == KIND_USER}
    pin_nodes = tuple(dict.fromkeys((*[i for i in seeds.pin_nodes
        if graph.node(i).kind != KIND_USER], *sorted(carrier_ids))))
    return replace(seeds, goal=goal, original_task=goal, constraints=constraints,
                   user_nodes=tuple(node.idx for node in users), pin_nodes=pin_nodes,
                   request_projection=True, request_source=source,
                   bound_goal_status=provenance.get("status", ""),
                   bound_goal_revision=provenance.get("revision"),
                   request_text=(latest.text if lossless else strip_machine_blocks(latest.text, preserve_layout=True))
                   if source >= 0 else ""), provenance
