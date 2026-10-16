"""Policy admission for lifecycle operations and explicit publication."""
from pathlib import Path


def evaluate(name, payload, *, cwd, allowed_paths=None):
    from permissions.policy import evaluate_policy, PolicyDecision, PermissionDecision
    from engine.agent_runtime import actor, enabled
    if not enabled():
        return PolicyDecision(PermissionDecision.DENY, "agent_runtime_disabled")
    if name == "agent_control":
        if (payload or {}).get("action") in ("resume", "retry"):
            return evaluate_policy("Agent", payload, cwd=cwd, allowed_paths=allowed_paths)
        return PolicyDecision(PermissionDecision.ALLOW, "agent_control_read_or_stop")
    from engine.agent_run_store import AgentRunStore
    from engine.agent_workspaces import _target
    sid, sender = actor()
    row = AgentRunStore().get(sid, str((payload or {}).get("agent_id") or ""))
    if sender != "parent" or not row or row["attempt"] != (payload or {}).get("attempt_id"):
        return PolicyDecision(PermissionDecision.DENY, "invalid_artifact_owner")
    artifact = row["artifact"]
    if row["state"] != "completed" or not artifact:
        return PolicyDecision(PermissionDecision.DENY, "artifact_not_ready")
    if Path(cwd).resolve() != Path(artifact["source_cwd"]).resolve():
        return PolicyDecision(PermissionDecision.DENY, "source_workspace_mismatch")
    asks = []
    try:
        for name in artifact["changed_files"]:
            path = _target(Path(artifact["repo"]), name, artifact)
            decision = evaluate_policy("Write", {"file_path": str(path)}, cwd=cwd, allowed_paths=allowed_paths)
            if decision.decision == PermissionDecision.DENY:
                return decision
            if decision.decision == PermissionDecision.ASK:
                asks.append(name)
    except (OSError, RuntimeError, ValueError) as exc:
        return PolicyDecision(PermissionDecision.DENY, str(exc))
    if asks:
        return PolicyDecision(PermissionDecision.ASK, "agent_publication_confirmation",
            matched_rule="agent_publication_ask", prompt="合入 Agent 分支的文件变更：" + ", ".join(asks))
    return PolicyDecision(PermissionDecision.ALLOW, "agent_publication_paths_allowed")
