"""Opt-in facts derived from execution predicates, not parallel declarations."""
from __future__ import annotations
import os
from pathlib import Path

ENV = "XEYO_EXECUTION_FACT_CONTRACTS"


def enabled():
    return os.environ.get(ENV, "").strip().lower() in {"1", "true", "on", "yes"}


def tool_receipt(result):
    receipt = result.execution_metadata() if enabled() else None
    # Acceptance travels with the actual result, not with the model's input.
    from memory.wsc_timing import enabled as timing_enabled
    request = (result.metadata or {}).get("compaction_request")
    if timing_enabled() and isinstance(request, dict) and not result.is_error and result.status == "ok":
        receipt = {**(receipt or result.execution_metadata()), "compaction_request": dict(request)}
    from synaptic.task_checkpoint import enabled as continuity_enabled
    for key in ("read_observation", "grep_observation"):
        observation = (result.metadata or {}).get(key)
        if continuity_enabled() and isinstance(observation, dict):
            receipt = {**(receipt or result.execution_metadata()), key: observation}
    return receipt


def scratch_allowed(path, cwd):
    if not enabled() or not cwd:
        return False
    root = Path(cwd).resolve()
    target = Path(path)
    target = (root / target if not target.is_absolute() else target).resolve()
    scratch = root / ".xeyo" / "tmp"
    try:
        relative = target.relative_to(scratch)
    except ValueError:
        return False
    # The reserved subtree itself cannot redirect outside the workspace.
    if scratch.resolve() != scratch:
        return False
    return not any(part.casefold() in {".git", ".xeyo", ".agents"} for part in relative.parts)


def writable(path, cwd):
    from permissions.filesystem import default_permission_context, check_write_permission_for_path, PermissionDecision
    from engine.write_store import WriteStore
    try:
        target = WriteStore(cwd)._canon(path)
        if check_write_permission_for_path(str(target), context=default_permission_context(cwd)) != PermissionDecision.ALLOW:
            return False
        parent = target
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
    except Exception:
        return False


def denial_text(decision, tool_input):
    message = f"Permission denied: {decision.reason}; rule={decision.matched_rule or 'unknown'}"
    if decision.reason == "bash_secret_read":
        from permissions.bash_secret_evidence import match as secret_match
        match = secret_match(str(tool_input.get("command") or ""))
        if match:
            # Category and location, never credentials or command contents.
            message += f"; evidence=credential_path; normalized_span={match.start()}:{match.end()}"
    elif decision.reason == "bash_write_target_unproven":
        message += "; evidence=write_target_not_resolved"
    return message
