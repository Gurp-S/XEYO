"""Compatibility for GUI inbox operations; durable runs remain authoritative."""


def store_for(session_id, agent_id):
    from engine.agent_runtime import enabled
    if not enabled():
        return None
    from engine.agent_run_store import AgentRunStore
    store = AgentRunStore()
    return store if store.get(session_id, agent_id) else None


def migrate_legacy(store, session_id, agent_id):
    import uuid
    import json
    import hashlib
    from engine import live_agents
    from engine.subagent_meta import META_LOCKS, meta_lock_key
    from engine.subagent_runner import _meta_path, upsert_subagent_meta
    key = live_agents._key(session_id, agent_id)
    with META_LOCKS.acquire(meta_lock_key(session_id, agent_id)), live_agents._lock:
        path = _meta_path(session_id, agent_id)
        meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        pending = [str(item) for item in meta.get("pending_followups", []) if str(item).strip()]
        queue = live_agents._INBOX.get(key, [])
        if not queue and not pending:
            return
        for item in queue:
            item["message_id"] = item.get("message_id") or uuid.uuid4().hex
        generation = meta.get("pending_followups_generation") or hashlib.sha256(json.dumps(pending).encode()).hexdigest()
        store.import_legacy(session_id, agent_id, generation, queue, pending)
        live_agents._INBOX.pop(key, None)
        if pending:
            upsert_subagent_meta(session_id, agent_id=agent_id,
                task_desc=str(meta.get("task_desc") or ""), status=str(meta.get("status") or "failed"),
                pending_followups=[])


def followup_generation(existing, pending):
    import uuid
    current = existing.get("pending_followups_generation")
    return (current if current and pending == list(existing.get("pending_followups") or [])
            else uuid.uuid4().hex)
