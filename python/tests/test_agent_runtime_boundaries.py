"""Boundary regressions through real storage, tools and HTTP adapters."""
import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.abort import AbortController
from engine.agent_identity import AgentBusy, AgentIdentity
from engine.agent_run_store import AgentRunStore
from engine.workspace_context import ExecutionContext, bind_workspace_context
from session.message_store import MessageStore
from tests.test_agent_runtime_v2 import repository, spec, runtime_enabled


def test_staged_deletion_is_absent_from_child_snapshot(tmp_path):
    from engine.agent_workspaces import prepare
    root, git = repository(tmp_path)
    git("rm", "f.txt")
    index = git("ls-files", "--stage")
    artifact = prepare(AgentIdentity("s", "a", "1"), spec(root, scope=["f.txt"], isolation="worktree"))
    assert not (Path(artifact["worktree"]) / "f.txt").exists()
    assert git("ls-files", "--stage") == index


def test_withdrawal_cannot_report_success_during_transcript_delivery(tmp_path, monkeypatch):
    from engine.agent_mailbox import deliver_sync
    transcript = importlib.import_module("session.record_transcript")
    original = transcript.record_transcript_sync
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    removed = []
    def persist(*args, **kwargs):
        removed.append(store.remove_message("s", "a", message_id="m"))
        return original(*args, **kwargs)
    monkeypatch.setattr(transcript, "record_transcript_sync", persist)
    try:
        store.send("s", "a", "parent", "message", message_id="m")
        assert deliver_sync(MessageStore(), "s", "a", identity.attempt_id) == 1
        assert removed == [False]
    finally:
        store.finish(identity, "completed", {})
        lease.release()


def test_stale_delivery_cannot_write_new_attempt_transcript(tmp_path):
    from engine.agent_mailbox import deliver_sync
    store = AgentRunStore()
    first, lease = store.start("s", "a", spec(tmp_path))
    store.finish(first, "completed", {})
    lease.release()
    second, lease = store.start("s", "a", spec(tmp_path))
    store.send("s", "a", "parent", "new attempt only")
    messages = MessageStore()
    try:
        with pytest.raises(AgentBusy, match="stale_agent_attempt"):
            deliver_sync(messages, "s", "a", first.attempt_id)
        assert messages.items == []
    finally:
        store.finish(second, "completed", {})
        lease.release()


def test_parent_withdrawal_is_scoped_to_parent_sender(tmp_path):
    store = AgentRunStore()
    a, la = store.start("s", "a", spec(tmp_path))
    b, lb = store.start("s", "b", spec(tmp_path))
    try:
        store.send("s", "b", "a", "peer", message_id="same")
        store.send("s", "b", "parent", "user", message_id="same")
        assert store.remove_message("s", "b", message_id="same")
        assert [r["text"] for r in store.pending("s", "b")] == ["peer"]
    finally:
        store.finish(a, "completed", {})
        store.finish(b, "completed", {})
        la.release()
        lb.release()


def test_incomplete_publication_cannot_be_overwritten_by_resume(tmp_path):
    from engine import agent_workspaces as ws
    root, _ = repository(tmp_path)
    store = AgentRunStore()
    run_spec = spec(root, scope=["f.txt"], isolation="worktree")
    identity, lease = store.start("s", "a", run_spec)
    artifact = ws.prepare(identity, run_spec)
    (Path(artifact["worktree"]) / "f.txt").write_text("change")
    artifact = ws.collect(artifact)
    store.artifact(identity, artifact)
    store.finish(identity, "completed", {})
    lease.release()
    ws._save(Path(artifact["directory"]) / "publication.json", {"state": "applying", "head": artifact["head"]})
    replacement = None
    try:
        with pytest.raises(AgentBusy, match="publication_recovery_required"):
            _, replacement = store.start("s", "a", run_spec)
        assert store.get("s", "a")["attempt"] == identity.attempt_id
    finally:
        if replacement:
            replacement.release()


def test_applied_journal_reconciles_db_before_resume(tmp_path):
    from engine import agent_workspaces as ws
    root, _ = repository(tmp_path)
    run_spec = spec(root, scope=["f.txt"], isolation="worktree")
    artifact = ws.prepare(AgentIdentity("s", "a", "1"), run_spec)
    (Path(artifact["worktree"]) / "f.txt").write_text("change")
    artifact = ws.collect(artifact)
    ws.publish(artifact)  # Process exits before the caller saves the DB receipt.
    resumed = ws.prepare(AgentIdentity("s", "a", "2"), run_spec, {"artifact": artifact})
    assert resumed["base"] == artifact["head"]
    assert resumed["applied_head"] == ""


@pytest.mark.asyncio
async def test_http_retry_obeys_workspace_deny(tmp_path, monkeypatch):
    from server.routers import sessions
    from tools.agent_tool import AgentTool
    from tools.base_tool import ToolResult
    from tools.tool_registry import ToolRegistry
    from permissions.policy import set_permission_mode
    (tmp_path / ".xeyo-policy.json").write_text(json.dumps({"deny_tools": ["Agent"]}))
    set_permission_mode("never")
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    store.finish(identity, "failed", {})
    lease.release()
    calls = []
    async def execute(self, payload, abort):
        calls.append(payload)
        return ToolResult("called")
    monkeypatch.setattr(AgentTool, "execute", execute)
    tool = AgentTool(cwd=str(tmp_path), session_id="s")
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(tool)
    engine = SimpleNamespace(_tools=registry, permission_profile="workspace_write")
    ended = []
    monkeypatch.setattr(sessions, "_pool", SimpleNamespace(try_begin=lambda sid: "lease", end=lambda *a: ended.append(a), get_if_present=lambda sid: engine))
    result = await sessions.session_agent_retry("s", "a", None, None, None, None)
    assert result["is_error"] and calls == []
    assert ended == [("s", "lease")]


@pytest.mark.asyncio
async def test_cancelled_wait_does_not_poison_future_observation(tmp_path):
    from tools.catalog import build_default_registry
    from msgtypes.message import ToolUse
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    registry = build_default_registry(cwd=str(tmp_path))
    payload = {"action": "wait", "agent_id": "a", "timeout_s": 60}
    try:
        with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
            waiting = asyncio.create_task(registry.run(ToolUse("wait1", "agent_control", payload), AbortController()))
            await asyncio.sleep(.15)
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            store.finish(identity, "completed", {})
            result = await registry.run(ToolUse("wait2", "agent_control", payload), AbortController())
            assert not result.is_error, result.content
            assert json.loads(result.content)["state"] == "completed"
    finally:
        lease.release()


@pytest.mark.asyncio
async def test_resume_admission_fences_attempt_replaced_after_read(tmp_path, monkeypatch):
    from engine.agent_runtime import dispatch
    from tools.agent_tool import AgentTool
    store = AgentRunStore()
    first, lease = store.start("s", "a", spec(tmp_path))
    store.finish(first, "completed", {})
    lease.release()
    original_start = AgentRunStore.start
    replacement = []
    def interleaved(self, session, agent, run_spec, **kwargs):
        if not replacement:
            second, owner = original_start(self, session, agent, run_spec)
            self.finish(second, "completed", {})
            owner.release()
            replacement.append(second)
        return original_start(self, session, agent, run_spec, **kwargs)
    monkeypatch.setattr(AgentRunStore, "start", interleaved)
    tool = AgentTool(cwd=str(tmp_path), session_id="s")
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        result = await dispatch(tool, {"reuse_agent_id": "a", "background": False}, AbortController())
    assert "stale_agent_attempt" in result.content
    assert store.get("s", "a")["attempt"] == replacement[0].attempt_id


def test_recovering_claim_is_replayed_once_after_transcript_failure(tmp_path, monkeypatch):
    from engine.agent_mailbox import deliver_sync
    transcript = importlib.import_module("session.record_transcript")
    original = transcript.flush_transcript
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    store.send("s", "a", "parent", "recover", message_id="m")
    messages = MessageStore()
    def fail(*a, **kw):
        raise OSError("flush failed")
    try:
        monkeypatch.setattr(transcript, "flush_transcript", fail)
        with pytest.raises(OSError):
            deliver_sync(messages, "s", "a", identity.attempt_id)
        assert not store.remove_message("s", "a", message_id="m")
        monkeypatch.setattr(transcript, "flush_transcript", original)
        assert deliver_sync(messages, "s", "a", identity.attempt_id) == 1
        assert len(messages.items) == 1
    finally:
        store.finish(identity, "completed", {})
        lease.release()


@pytest.mark.asyncio
async def test_parallel_workers_do_not_share_unresolved_operation_keys(tmp_path):
    from engine.agent_identity import current_agent, child_execution_context
    from tools.tool_registry import ToolRegistry
    from tools.base_tool import ToolResult
    from msgtypes.message import ToolUse
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    class Mutation:
        name = "FixtureMutation"
        async def execute(self, payload, abort):
            calls.append(current_agent.get().agent_id)
            if len(calls) == 1:
                started.set()
                await release.wait()
            return ToolResult("done")
    async def call(aid):
        token = current_agent.set(AgentIdentity("s", aid, aid + "-attempt"))
        try:
            with child_execution_context(tmp_path / aid, "s", aid):
                return await ToolRegistry()._execute_audited(Mutation(), ToolUse(aid, "FixtureMutation", {"path": "same"}), AbortController())
        finally:
            current_agent.reset(token)
    first = asyncio.create_task(call("a"))
    try:
        await started.wait()
        result = await call("b")
        assert not result.is_error, result.content
        assert calls == ["a", "b"]
    finally:
        release.set()
        await first


@pytest.mark.asyncio
async def test_registry_can_recover_an_unknown_publication(tmp_path):
    from engine import agent_workspaces as ws
    from engine.action_journal import ActionJournal, action_identity
    from tools.execution_outcome import operation_key
    from tools.catalog import build_default_registry
    from msgtypes.message import ToolUse
    from permissions.policy import set_permission_mode
    root, _ = repository(tmp_path)
    store = AgentRunStore()
    run_spec = spec(root, scope=["f.txt"], isolation="worktree")
    identity, lease = store.start("s", "a", run_spec)
    artifact = ws.prepare(identity, run_spec)
    (Path(artifact["worktree"]) / "f.txt").write_text("publish")
    artifact = ws.collect(artifact)
    store.artifact(identity, artifact)
    store.finish(identity, "completed", {})
    lease.release()
    payload = {"agent_id": "a", "attempt_id": identity.attempt_id}
    aid, key = action_identity(session_id="s", turn_id="old", tool_use_id="old", tool_name="agent_apply", tool_input=payload)
    journal = ActionJournal("s")
    journal.begin(action_id=aid, idempotency_key=key, turn_id="old", tool_use_id="old", tool_name="agent_apply", side_effect="write", operation_key=operation_key("s", "agent_apply", payload))
    journal.unknown(aid, "process exited")
    set_permission_mode("never")
    with bind_workspace_context(ExecutionContext("s", str(root))):
        result = await build_default_registry(cwd=str(root)).run(ToolUse("retry", "agent_apply", payload), AbortController())
    assert not result.is_error, result.content
    assert (root / "f.txt").read_text() == "publish"
    assert journal.summary()["counts"].get("unknown", 0) == 0


def test_owner_crash_recovers_worktree_before_db_receipt(tmp_path):
    import subprocess
    import sys
    root, _ = repository(tmp_path)
    store = AgentRunStore()
    script = """
import os, sys
from pathlib import Path
from engine.agent_run_store import AgentRunStore
from engine.agent_workspaces import prepare
spec = dict(cwd=sys.argv[1], task_id='task', desc='fixture', scope=['f.txt'], isolation='worktree')
identity, lease = AgentRunStore().start('s', 'a', spec)
artifact = prepare(identity, spec)
(Path(artifact['worktree']) / 'f.txt').write_text('crashed worker')
os._exit(23)
"""
    exited = subprocess.run([sys.executable, "-c", script, str(root)], timeout=30, capture_output=True)
    assert exited.returncode == 23, exited.stderr.decode(errors="replace")
    store.recover()
    row = store.get("s", "a")
    assert row["state"] == "interrupted"
    assert row["artifact"] and row["artifact"]["changed_files"] == ["f.txt"]
    assert (root / "f.txt").read_text() == "base\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_one_shot_cli_owns_background_until_terminal(tmp_path, monkeypatch, failed):
    from cli import chat_cmd
    from tools.agent_tool import AgentTool
    from tools.base_tool import ToolResult
    from engine.agent_runtime import shutdown
    started, release = asyncio.Event(), asyncio.Event()
    tool = AgentTool(cwd=str(tmp_path), session_id="s")
    async def child(self, payload, abort):
        started.set()
        await release.wait()
        return ToolResult("child result", is_error=failed)
    monkeypatch.setattr(AgentTool, "_execute_legacy", child)
    class Engine:
        session_id = "s"
        async def submit(self, text, options):
            with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
                await tool.execute({"desc": "task", "background": True}, AbortController())
            if False:
                yield None
    monkeypatch.setattr(chat_cmd, "ensure_utf8_stdio", lambda: None)
    monkeypatch.setattr(chat_cmd, "resolve_cwd", lambda cwd, persist: cwd)
    monkeypatch.setattr(chat_cmd, "build_chat_engine", lambda **kwargs: (Engine(), 0))
    task = asyncio.create_task(chat_cmd.chat_async(prompt="task", cwd=str(tmp_path), session_id="s",
        provider="fake", model="fake", api_key="", base_url="", permission_mode="never",
        agent_mode="agent", print_mode=True, json_mode=True))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.sleep(.05)
        assert not task.done(), "CLI exited while its background agent was running"
        release.set()
        assert await task == (1 if failed else 0)
    finally:
        release.set()
        await task
        await shutdown()


def test_task_graph_publication_has_no_partial_visible_batch(tmp_path, monkeypatch):
    from coord import file_store
    from coord.planner import Planner
    store = file_store.CoordFileStore(tmp_path)
    observed = []
    original = file_store._atomic_write_json
    def write(path, data):
        result = original(path, data)
        observed.append({t.task_id for t in store.list_tasks()})
        return result
    monkeypatch.setattr(file_store, "_atomic_write_json", write)
    report = Planner(tmp_path, store).plan_round([
        {"task_id": "task_a", "scope": ["a"], "deps": ["task_b"]},
        {"task_id": "task_b", "scope": ["b"]},
    ])
    assert len(report["created"]) == 2
    assert observed and all(ids in (set(), {"task_a", "task_b"}) for ids in observed)


@pytest.mark.asyncio
async def test_http_retry_stop_before_admission_reaches_agent(tmp_path, monkeypatch):
    from server.routers import sessions
    from server.session_pool import SessionPool
    from tools.agent_tool import AgentTool
    from tools.base_tool import ToolResult
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    store.finish(identity, "failed", {})
    lease.release()
    seen = []
    async def execute(self, payload, abort):
        seen.append(abort.aborted)
        return ToolResult("cancelled", is_error=abort.aborted)
    monkeypatch.setattr(AgentTool, "execute", execute)
    engine = SimpleNamespace(_tools={"Agent": AgentTool(cwd=str(tmp_path), session_id="s")}, permission_profile="workspace_write")
    pool = SessionPool(cwd=str(tmp_path))
    def get_engine(sid):
        pool.interrupt(sid)
        return engine
    monkeypatch.setattr(pool, "get_if_present", get_engine)
    monkeypatch.setattr(sessions, "_pool", pool)
    result = await sessions.session_agent_retry("s", "a", None, None, None, None)
    assert result["is_error"] and (not seen or seen == [True])
    assert not pool.is_busy("s") and not pool.batch_is_active("s")


def test_task_graph_owner_is_not_stolen_when_lock_timestamp_is_old(tmp_path):
    import os
    from coord.file_store import CoordFileStore
    from coord.task_dependencies import graph_guard
    store = CoordFileStore(tmp_path)
    with graph_guard(store) as first:
        assert first
        paths = list(store.coord_dir.rglob("*.lock"))
        assert paths
        for path in paths:
            os.utime(path, (1, 1))
        with graph_guard(store) as second:
            assert not second


def test_failed_graph_batch_and_corrupt_transition_do_not_publish_partial_state(tmp_path, monkeypatch):
    from coord import file_store
    from coord.planner import Planner
    store = file_store.CoordFileStore(tmp_path)
    planner = Planner(tmp_path, store)
    original = file_store._atomic_write_json
    monkeypatch.setattr(file_store, "_atomic_write_json", lambda *a: False)
    with pytest.raises(OSError, match="persistence"):
        planner.plan_round([{"task_id": "task_a", "scope": ["a"]}])
    assert store.list_tasks() == []
    monkeypatch.setattr(file_store, "_atomic_write_json", original)
    planner.plan_round([{"task_id": "task_a", "scope": ["a"]}])
    task = store.load_task("task_a")
    task.status = "completed"
    store._save_task(task)
    store._task_path(task.task_id).write_text("broken")
    with pytest.raises(OSError, match="invalid_task_snapshot"):
        store.load_task(task.task_id)


@pytest.mark.asyncio
async def test_http_retry_real_registry_model_loop_and_worktree(tmp_path, monkeypatch):
    from fastapi import FastAPI
    import httpx
    from server.routers import sessions
    from server.session_pool import SessionPool
    from engine.query_engine import build_default_engine
    from engine.shared_budget import current_budget
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    root, _ = repository(tmp_path)
    store = AgentRunStore()
    run_spec = spec(root, scope=["f.txt"], isolation="worktree")
    identity, lease = store.start("s", "a", run_spec)
    store.finish(identity, "failed", {})
    lease.release()
    class Model:
        last_usage = None
        calls = 0
        async def stream(self, messages, tools, abort):
            assert current_budget.get().usd_limit == 2
            self.calls += 1
            if self.calls == 1:
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("r", "Read", {"file_path": "f.txt"}))
            elif self.calls == 2:
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("w", "Write", {"file_path": "f.txt", "content": "http worker"}))
            else:
                yield ModelChunk(kind="text_delta", text="done")
    monkeypatch.setattr("model.fake.FakeModelClient", Model)
    engine = build_default_engine(cwd=str(root), session_id="s", model_backend="fake", max_turns=5)
    engine.config["max_budget_usd"] = 2
    pool = SessionPool(cwd=str(root))
    monkeypatch.setattr(pool, "get_if_present", lambda sid: engine)
    monkeypatch.setattr(sessions, "_pool", pool)
    app = FastAPI()
    app.include_router(sessions.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/sessions/s/agents/a/retry", json={"attempt_id": identity.attempt_id})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done", response.text
    row = store.get("s", "a")
    assert row["attempt"] == response.json()["attempt_id"] != identity.attempt_id
    assert (Path(row["artifact"]["worktree"]) / "f.txt").read_text() == "http worker"
    assert (root / "f.txt").read_text() == "base\n"
    assert not pool.is_busy("s") and not pool.batch_is_active("s")


def test_legacy_metadata_followups_migrate_once_with_queue_overlap(tmp_path, monkeypatch):
    from engine.agent_live_bridge import migrate_legacy
    from engine import live_agents
    from engine.subagent_runner import upsert_subagent_meta
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    upsert_subagent_meta("s", agent_id="a", task_desc="old", status="failed", pending_followups=["same", "same", "metadata only"])
    key = live_agents._key("s", "a")
    live_agents._INBOX[key] = [{"text": "same", "message_id": "legacy"}]
    # A failed metadata cleanup must not replay an already committed import.
    monkeypatch.setattr("engine.subagent_runner.upsert_subagent_meta", lambda *a, **kw: None)
    try:
        migrate_legacy(store, "s", "a")
        assert [r["text"] for r in store.pending("s", "a")] == ["same", "same", "metadata only"]
        migrate_legacy(store, "s", "a")
        assert len(store.pending("s", "a")) == 3
        # A later legacy batch with identical text has a new generation.
        upsert_subagent_meta("s", agent_id="a", task_desc="old", status="failed", pending_followups=[])
        upsert_subagent_meta("s", agent_id="a", task_desc="old", status="failed", pending_followups=["metadata only"])
        migrate_legacy(store, "s", "a")
        assert len(store.pending("s", "a")) == 4
    finally:
        live_agents._INBOX.pop(key, None)
        store.finish(identity, "completed", {})
        lease.release()
