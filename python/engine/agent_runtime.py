"""Agent lifetime, independent of a calling tool's foreground/background mode.

Only this module owns async tasks. The durable store owns identity, messages and
admission; existing AgentTool owns model execution and product progress events.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
import json
import os
import uuid

from engine.abort import AbortController, LinkedAbortController
from engine.agent_identity import AgentBusy, current_agent
from engine.agent_run_store import AgentRunStore, ACTIVE
from tools.base_tool import ToolResult


def enabled():
    from engine.flag_definitions import enabled as flag
    return flag("XEYO_AGENT_RUNTIME_V2")


def actor():
    from engine.workspace_context import get_execution_context
    identity = current_agent.get()
    ctx = get_execution_context()
    return ((identity.session_id, identity.agent_id) if identity else
            (ctx.session_id if ctx else "", "parent"))


def result(value, *, error=False):
    return ToolResult(content=json.dumps(value, ensure_ascii=False), is_error=error,
                      metadata=value, status="error" if error else "ok")


@dataclass
class RunningAgent:
    identity: object
    abort: AbortController
    task: asyncio.Task | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)


_running: dict[tuple[str, str, str], RunningAgent] = {}


def _key(identity):
    return identity.session_id, identity.agent_id, identity.attempt_id


def running(session, agent, attempt=""):
    return next((r for (sid, aid, run), r in tuple(_running.items())
                 if sid == session and aid == agent and (not attempt or attempt == run)), None)


def cancel(session, agent, attempt=""):
    run = running(session, agent, attempt)
    if run is None:
        return False
    run.abort.abort("agent_interrupted")
    if run.task and run.started.is_set():
        run.task.get_loop().call_soon_threadsafe(run.task.cancel)
    return True


def session_active(session):
    return any(sid == session for sid, _, _ in tuple(_running))


def cancel_session(session):
    for run in tuple(_running.values()):
        if run.identity.session_id == session:
            cancel(session, run.identity.agent_id, run.identity.attempt_id)


async def dispatch(tool, payload, abort):
    from engine.agent_admission import dispatch as owned_dispatch
    return await owned_dispatch(_dispatch, tool, payload, abort)


async def _dispatch(tool, payload, abort):
    abort.raise_if_aborted()
    if current_agent.get() is not None:
        return result({"error": "nested_agent_spawn_unavailable"}, error=True)
    from permissions.write_scope import normalize_worker_scope
    from engine.workspace_context import get_execution_context
    from common.concurrency_budget import agent_spawn_limit
    from tools.agent_tool.agent_tool import _safe_agent_id
    sid = tool._session_id or actor()[0]
    if not sid:
        return result({"error": "missing_session_identity"}, error=True)
    if actor()[0] and actor()[0] != sid:
        return result({"error": "session_identity_mismatch"}, error=True)
    store = await asyncio.to_thread(AgentRunStore)
    spec = dict(payload)
    reuse = str(spec.get("reuse_agent_id") or "").strip()
    previous = await asyncio.to_thread(store.get, sid, reuse) if reuse else None
    expected = spec.pop("reuse_attempt_id", None)
    if expected is not None and expected != (previous["attempt"] if previous else ""):
        return result({"error": "stale_agent_attempt"}, error=True)
    expected = previous["attempt"] if previous else ""
    if previous:
        # Only explicit fields override an immutable persisted run specification.
        spec = {**previous["spec"], **spec}
    spec["cwd"] = tool._cwd
    scopes, _, reason = normalize_worker_scope(spec.get("scope") or [], cwd=tool._cwd)
    if spec.get("scope") and not scopes:
        return result({"error": reason or "invalid_write_scope"}, error=True)
    ctx = get_execution_context()
    from permissions.policy import session_permission_profile
    if scopes and (ctx is None or session_permission_profile() == "readonly"):
        return result({"error": "Permission denied: read-only session"}, error=True)
    spec["scope"] = scopes
    isolation = spec.get("isolation") or ("worktree" if scopes else "shared")
    if isolation not in ("worktree", "shared"):
        return result({"error": "invalid_isolation"}, error=True)
    if isolation == "worktree" and ctx is not None and ctx.runtime != "local":
        return result({"error": "worktree_runtime_unavailable", "runtime": ctx.runtime}, error=True)
    spec["isolation"] = isolation
    if previous:
        original = previous["spec"]
        for field in ("cwd", "scope", "isolation", "required_tools", "agent_type"):
            if spec.get(field) != original.get(field):
                return result({"error": "agent_spec_changed", "field": field}, error=True)
    spec.setdefault("task_id", "task")
    spec.setdefault("desc", "")
    agent = reuse or _safe_agent_id(str(spec["task_id"]), tail=uuid.uuid4().hex[:12])
    if len(agent) > 180 or any(c in agent for c in "/\\") or agent in (".", "..", "parent"):
        return result({"error": "invalid_agent_identity"}, error=True)
    try:
        total = max(1, int(os.environ.get("XEYO_MAX_TOTAL_AGENTS", "32")))
    except ValueError:
        total = 32
    # Snapshot before acquiring resources; a broken provider cannot strand a lease.
    owned_tool = copy.copy(tool)
    from engine.agent_model import fork_runtime
    runtime = fork_runtime(tool._get_runtime())
    owned_tool._runtime_provider = lambda: runtime
    owned_tool._session_id = sid
    admission = asyncio.create_task(asyncio.to_thread(store.start, sid, agent, spec,
                                                  session_limit=agent_spawn_limit(), total_limit=total,
                                                  expected_attempt=expected))
    from engine.agent_io import owned_io, wait_owned
    try:
        (identity, lease), cancelled = await wait_owned(admission)
    except (AgentBusy, ValueError) as exc:
        return result({"error": str(exc), "agent_id": agent}, error=True)
    if cancelled:
        try:
            await owned_io(store.finish, identity, "cancelled", {"error": "admission cancelled"})
        finally:
            lease.release()
        raise asyncio.CancelledError
    run = RunningAgent(identity, LinkedAbortController(abort))
    _running[_key(identity)] = run
    background = bool(spec.get("background", True))
    if background:
        try:
            owned_tool._emit_xy({"type": "multi_agent_task", "task_id": spec["task_id"],
                "uid": f"{spec['task_id']}:{agent.rsplit('-', 1)[-1]}", "agent_id": agent,
                "desc": str(spec["desc"])[:120], "status": "running", "scope": scopes,
                "read_only": not bool(scopes), "attempt_id": identity.attempt_id,
                "attempt_started_at": int(identity.created_at * 1000)})
        except Exception:
            import logging
            logging.getLogger(__name__).warning("agent progress publication failed", exc_info=True)

    async def execute():
        token = current_agent.set(identity)
        from tools.progress_sink import set_progress_sink, reset_progress_sink
        progress_token = set_progress_sink(None) if background else None
        state, final = "interrupted", {"error": "execution interrupted"}
        try:
            run.started.set()
            from engine.agent_live_bridge import migrate_legacy
            from engine.agent_io import owned_io
            await owned_io(migrate_legacy, store, sid, agent)
            request = {**spec, "reuse_agent_id": agent, "background": False,
                       "isolation": "" if isolation == "shared" else isolation}
            output = await owned_tool._execute_legacy(request, run.abort)
            output.metadata = {**(output.metadata or {}), "agent_id": agent, "attempt_id": identity.attempt_id}
            final = {"content": output.content, "is_error": output.is_error,
                     "metadata": output.metadata or {}}
            stop = str((output.metadata or {}).get("stop_reason") or "")
            state = ("cancelled" if run.abort.aborted else "failed" if output.is_error or
                     stop in ("error", "budget", "budget_usd", "max_turns", "max_tool_calling", "aborted", "timeout")
                     else "completed")
            if state != "completed" and not output.is_error:
                output.is_error, output.status = True, "error"
                output.content = output.content.replace("[Agent tool_result status=OK", "[Agent tool_result status=ERROR", 1)
                final.update(is_error=True, content=output.content)
            return output
        except asyncio.CancelledError:
            run.abort.abort("agent_task_cancelled")
            state = "cancelled"
            raise
        except Exception as exc:
            state = "cancelled" if run.abort.aborted else "failed"
            final = {"error": f"{type(exc).__name__}: {exc}"}
            return result(final, error=True)
        finally:
            try:
                # Shield durable settlement: release ownership only after settlement
                # has finished, including when the foreground caller is cancelled.
                await owned_io(store.finish, identity, state, final)
            finally:
                _running.pop(_key(identity), None)
                lease.release()
                if progress_token is not None:
                    reset_progress_sink(progress_token)
                current_agent.reset(token)

    run.task = asyncio.create_task(execute(), name=f"agent:{sid}:{agent}:{identity.attempt_id}")
    from engine.agent_task_wait import wait_for_agent
    output = await wait_for_agent(run, foreground=not background)
    if output is not None:
        return output
    return result({"agent_id": agent, "attempt_id": identity.attempt_id,
                   "state": "running", "isolation": isolation, "scope": scopes})


async def control(payload, abort, *, agent_tool=None):
    sid, sender = actor()
    if not sid:
        return result({"error": "missing_session_identity"}, error=True)
    store = await asyncio.to_thread(AgentRunStore)
    await asyncio.to_thread(store.recover)
    action = str(payload.get("action") or "list")
    if action == "list":
        rows = await asyncio.to_thread(store.list, sid)
        return result({"agents": [{k: r[k] for k in ("agent", "attempt", "state", "updated")}
                                   for r in rows]})
    aid = str(payload.get("agent_id") or "")
    row = await asyncio.to_thread(store.get, sid, aid)
    if row is None:
        return result({"error": "unknown_agent"}, error=True)
    expected = str(payload.get("attempt_id") or row["attempt"])
    if expected != row["attempt"]:
        return result({"error": "stale_agent_attempt"}, error=True)
    if action == "interrupt":
        if sender != "parent":
            return result({"error": "Permission denied: parent control required"}, error=True)
        found = cancel(sid, aid, expected)
        return result({"agent_id": aid, "attempt_id": expected, "cancellation_requested": found},
                      error=not found and row["state"] in ACTIVE)
    if action in ("resume", "retry"):
        if sender != "parent" or agent_tool is None:
            return result({"error": "Permission denied: parent control required"}, error=True)
        return await dispatch(agent_tool, {**row["spec"], "reuse_agent_id": aid,
                                          "reuse_attempt_id": expected,
                                          "background": bool(payload.get("background", True))}, abort)
    if action == "wait":
        seconds = min(60.0, max(0.0, float(payload.get("timeout_s", 30))))
        deadline = asyncio.get_running_loop().time() + seconds
        while row["state"] in ACTIVE and asyncio.get_running_loop().time() < deadline:
            abort.raise_if_aborted()
            if aid == sender:
                return result({"error": "self_wait_unavailable"}, error=True)
            await asyncio.sleep(min(.05, max(0, deadline - asyncio.get_running_loop().time())))
            row = await asyncio.to_thread(store.get, sid, aid)
            if row is None or row["attempt"] != expected:
                return result({"error": "stale_agent_attempt"}, error=True)
    elif action != "status":
        return result({"error": "unknown_agent_action"}, error=True)
    value = {k: row[k] for k in ("agent", "attempt", "state", "result")}
    artifact = row["artifact"]
    value["artifact"] = ({k: artifact[k] for k in ("worktree", "branch", "base", "head", "changed_files", "applied_head")}
                         if artifact else None)
    return result(value)


async def shutdown():
    from engine.agent_admission import stopping, drain
    from engine.agent_io import wait_owned
    with stopping():
        async def settle():
            await drain()
            await _shutdown_running()
        _, cancelled = await wait_owned(asyncio.create_task(settle()))
        if cancelled:
            raise asyncio.CancelledError


async def _shutdown_running():
    runs = list(_running.values())
    for run in runs:
        await run.started.wait()
        run.abort.abort("server_shutdown")
        if run.task:
            run.task.cancel()
    await asyncio.gather(*(r.task for r in runs if r.task), return_exceptions=True)
