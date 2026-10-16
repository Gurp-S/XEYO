"""Agent observation and mutation identities at the tool journal boundary."""
import json


def side_effect(name, payload):
    if name == "agent_control" and isinstance(payload, dict):
        if payload.get("action", "list") in ("list", "status", "wait"):
            return "none"
        return "process"
    if name == "agent_apply":
        return "write"
    return None


def operation_owner(session_id):
    from engine.agent_identity import current_agent
    identity = current_agent.get()
    if identity is None:
        return session_id
    # Stable across retries of this worker; independent from sibling workers.
    return json.dumps([session_id, identity.agent_id], separators=(",", ":"))


def owns_recovery(name, payload):
    if not isinstance(payload, dict):
        return False
    return bool((name == "agent_apply" and payload.get("agent_id") and payload.get("attempt_id")) or
                (name == "agent_send" and payload.get("message_id")))


def settle_recoveries(journal, action_id):
    from engine.action_journal import _lock_for, action_file_lock
    with _lock_for(journal.path), action_file_lock(journal.path):
        latest = journal._latest()
        receipt = latest.get(action_id, {})
        if receipt.get("status") != "completed" or receipt.get("result_is_error"):
            return
        fields = {k: value for k, value in receipt.items() if k.startswith("result_") or
                  k in ("status", "updated_at", "side_effect", "error_kind", "retryable")}
        for prior_id in receipt.get("recovery_of", []):
            if prior_id != action_id and latest.get(prior_id, {}).get("status") in ("executing", "unknown"):
                journal._append_locked({**fields, "action_id": prior_id, "recovered_by": action_id})
