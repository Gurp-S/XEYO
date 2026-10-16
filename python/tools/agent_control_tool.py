"""Agent lifecycle and worktree publication capabilities."""
import asyncio

from engine.agent_runtime import actor, control, result
from engine.agent_run_store import AgentRunStore, ACTIVE
from engine.agent_identity import AgentIdentity


class AgentControlTool:
    name = "agent_control"

    def __init__(self, cwd="."):
        self._cwd = cwd
        self._session_id = ""
        self._provider = None
        self._write_store = None

    def set_session_id(self, session_id):
        self._session_id = session_id

    def set_runtime_provider(self, provider):
        self._provider = provider

    def set_write_store(self, store):
        self._write_store = store

    @staticmethod
    def is_read_only():
        return False

    @staticmethod
    def is_concurrency_safe():
        return True

    def schema(self):
        return {"name": self.name, "description":
            "Session agent lifecycle: list, status, bounded wait, interrupt, resume or retry. "
            "Each execution has an attempt_id. Resume/retry preserve prior history and task scope. "
            "Only the parent can interrupt or start another execution. Waiting does not cancel the target.",
            "input_schema": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["list", "status", "wait", "interrupt", "resume", "retry"]},
                "agent_id": {"type": "string"}, "attempt_id": {"type": "string"},
                "timeout_s": {"type": "number", "minimum": 0, "maximum": 60},
                "background": {"type": "boolean", "default": True}}, "required": ["action"]}}

    async def execute(self, input, abort):
        from tools.agent_tool.agent_tool import AgentTool
        from engine.agent_runtime import enabled
        if not enabled():
            return result({"error": "agent_runtime_disabled"}, error=True)
        tool = AgentTool(cwd=self._cwd, session_id=self._session_id or actor()[0], write_store=self._write_store)
        tool.set_runtime_provider(self._provider)
        return await control(input, abort, agent_tool=tool)


class AgentApplyTool:
    name = "agent_apply"

    @staticmethod
    def is_read_only():
        return False

    @staticmethod
    def is_concurrency_safe():
        return False

    def schema(self):
        return {"name": self.name, "description":
            "Publish a completed agent's retained worktree changes to its source checkout. "
            "Requires an exact attempt_id, parent ownership, unchanged destination file versions "
            "and current write permissions. Conflicts leave both checkouts unchanged; the Git index is preserved.",
            "input_schema": {"type": "object", "properties": {
                "agent_id": {"type": "string"}, "attempt_id": {"type": "string"}},
                "required": ["agent_id", "attempt_id"]}}

    async def execute(self, input, abort):
        from engine.agent_runtime import enabled
        from engine.agent_workspaces import publish, _owned_io, _target
        from engine.workspace_context import get_execution_context
        from permissions.policy import evaluate_policy, PermissionDecision
        from pathlib import Path
        sid, sender = actor()
        if not enabled() or not sid or sender != "parent":
            return result({"error": "Permission denied: parent control required"}, error=True)
        aid, attempt = str(input.get("agent_id") or ""), str(input.get("attempt_id") or "")
        if not attempt:
            return result({"error": "missing_attempt_id"}, error=True)
        store = await asyncio.to_thread(AgentRunStore)
        lease = store.lease(sid, aid)
        try:
            await _owned_io(lease.acquire)
            row = await asyncio.to_thread(store.get, sid, aid)
            if not row or row["attempt"] != attempt or row["state"] != "completed" or not row["artifact"]:
                return result({"error": "artifact_not_ready"}, error=True)
            artifact = row["artifact"]
            ctx = get_execution_context()
            if ctx is None or Path(ctx.cwd).resolve() != Path(artifact["source_cwd"]).resolve():
                return result({"error": "Permission denied: source workspace mismatch"}, error=True)
            for name in artifact["changed_files"]:
                path = _target(Path(artifact["repo"]), name, artifact)
                decision = evaluate_policy("Write", {"file_path": str(path)}, cwd=ctx.cwd)
                from permissions.filesystem import permission_preapproved
                if (decision.decision == PermissionDecision.DENY or
                    (decision.decision == PermissionDecision.ASK and not permission_preapproved())):
                    return result({"error": "Permission denied: artifact path", "path": name}, error=True)
            abort.raise_if_aborted()
            def publish_owned():
                published = publish(artifact)
                store.artifact(AgentIdentity(sid, aid, attempt), published)
                return published
            artifact = await _owned_io(publish_owned)
            return result({"agent_id": aid, "attempt_id": attempt, "published": True,
                           "files": artifact["changed_files"], "branch": artifact["branch"]})
        except Exception as exc:
            return result({"error": str(exc)}, error=True)
        finally:
            lease.release()
