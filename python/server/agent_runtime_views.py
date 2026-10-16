"""Project durable runtime state into the existing agent-card API."""
from engine.agent_run_store import AgentRunStore, ACTIVE


def project_agents(session_id, legacy):
    from engine.agent_runtime import enabled
    if not enabled():
        return legacy
    store = AgentRunStore()
    store.recover()
    cards = {card["agentId"]: card for card in legacy}
    for row in store.list(session_id):
        aid, spec = row["agent"], row["spec"]
        final = row["result"] or {}
        metadata = final.get("metadata") or {}
        card = cards.setdefault(aid, {"agentId": aid, "taskId": spec.get("task_id", ""),
            "desc": spec.get("desc", ""), "startedAt": int(row["created"] * 1000),
            "hasTranscript": False, "tokensUsed": 0, "costCny": None, "costPartial": False})
        card.update(status="running" if row["state"] in ACTIVE else "done" if row["state"] == "completed" else "failed",
            attemptId=row["attempt"], runtimeState=row["state"], scope=spec.get("scope", []),
            startedAt=int(row["created"] * 1000), updatedAt=int(row["updated"] * 1000),
            readOnly=not bool(spec.get("scope")), inboxCount=len(store.pending(session_id, aid, limit=256)),
            resultPreview=str(final.get("content") or final.get("error") or card.get("resultPreview") or "")[:800])
        if metadata:
            card.update(tokensUsed=metadata.get("tokens_used", card["tokensUsed"]),
                        costCny=metadata.get("cost_cny"), costPartial=metadata.get("cost_partial", False))
        artifact = row["artifact"]
        if artifact:
            card["isolation"] = {key: artifact[key] for key in ("worktree", "branch", "changed_files", "applied_head")}
    return list(cards.values())
