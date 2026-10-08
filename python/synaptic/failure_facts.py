"""Deterministic failure identities; unknown scope stays per invocation."""
import hashlib
import json
import os
from dataclasses import replace

ENV = "XEYO_WSC_FAILURE_FACTS"


def enabled():
    from synaptic.task_checkpoint import enabled as continuity_enabled
    return continuity_enabled() or os.environ.get(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def identity(graph, node):
    from synaptic.path_origins import declared_paths
    category = "verdict_conflict" if node.execution_status == "ok" else (node.execution_error_kind or node.execution_status or "reported_failure")
    targets = declared_paths(node, graph)
    # Bash command equality is required even when two commands name the same file.
    # Directory-only calls are represented by the entire declared command, too.
    command = node.command.strip()
    # The original serialized invocation is the authority. Suffix display paths
    # must never merge distinct operations or different full-path targets.
    invocation = graph.use_signatures.get(node.tool_use_id, "")
    target = (invocation, command) if invocation else ()
    if not invocation:
        target = ("unknown", node.idx)
    return (node.tool_name or "unknown", category, target)


def project_groups(graph, indices):
    groups = {}
    for i in indices:
        key = identity(graph, graph.node(i))
        groups.setdefault(key, []).append(i)
    labels, sources, keys = [], [], []
    for key, members in groups.items():
        node = graph.node(members[-1])
        digest = hashlib.sha256(repr(key).encode()).hexdigest()
        tool, category, _ = key
        from synaptic.path_origins import declared_paths
        targets = declared_paths(node, graph)
        scope = (", ".join(targets) if targets else f"call={node.tool_use_id or node.idx}") if graph.use_signatures.get(node.tool_use_id) else f"source=#{node.idx}, target=unknown"
        label = f"{tool} {category} target={scope} identity={digest[:12]}"
        # No result prose determines category, identity, or deletion. Diagnostics
        # remain available through all exact source entrances, without rewriting.
        if len(members) > 1:
            label += f"（×{len(members)}）"
        labels.append(label)
        sources.append(tuple(members))
        keys.append(digest)
    return tuple(labels), tuple(sources), tuple(keys)


def working_facts(states):
    # Failure evidence is carried by the complete UNRESOLVED source groups.
    return tuple(replace(state, related_errors=()) for state in states)


def receipt_verdict(block):
    """Typed execution facts override textual guesses; legacy returns unknown."""
    if block.get("is_error") is True:
        return True
    execution = block.get("execution")
    if not isinstance(execution, dict):
        return None
    if execution.get("status") == "error":
        return True
    if execution.get("status") == "ok" and execution.get("complete") is True:
        return False
    return None


def denial(node):
    if node.execution_status:
        return node.execution_error_kind == "PERMISSION_DENIED"
    # Historical records without a typed verdict retain their existing evidence.
    from synaptic.verdicts import is_terminal_denial
    return is_terminal_denial(node.error_sig)


def ambiguous_calls(messages):
    from synaptic.textutil import tool_use_blocks
    first, ambiguous = {}, set()
    for message in messages:
        for use in tool_use_blocks(message):
            uid = str(use.get("id") or "")
            signature = json.dumps([use.get("name") or "tool", use.get("input")], ensure_ascii=False, sort_keys=True, default=str)
            if uid and uid in first and first[uid] != signature:
                ambiguous.add(uid)
            first[uid] = signature
    return ambiguous
