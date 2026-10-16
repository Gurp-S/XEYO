"""Real offline ownership/mailbox/worktree contracts; no provider calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from engine.abort import AbortController
from engine.agent_identity import AgentBusy, AgentIdentity, current_agent, child_execution_context
from engine.agent_run_store import AgentRunStore
from engine.workspace_context import ExecutionContext, bind_workspace_context, get_execution_context, update_execution_context
from tools.agent_tool.agent_tool import AgentTool, SubagentOutput


@pytest.fixture(autouse=True)
def runtime_enabled(monkeypatch):
    monkeypatch.setenv("XEYO_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("XEYO_DOCKER_CONTAINER", "")


def spec(tmp_path, *, scope=None, isolation="shared"):
    return {"cwd": str(tmp_path), "task_id": "task", "desc": "fixture",
            "scope": scope or [], "isolation": isolation}


def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@local")
    (root / ".gitignore").write_text(".xeyo/\n.tmp/\n.xy-shadow-git/\n")
    (root / "f.txt").write_text("base\n")
    git("add", ".")
    git("commit", "-m", "base")
    return root, git


def test_attempt_exclusion_and_fenced_settlement(tmp_path):
    store = AgentRunStore()
    first, lease = store.start("s", "worker", spec(tmp_path))
    try:
        with pytest.raises(AgentBusy):
            store.start("s", "worker", spec(tmp_path))
        store.recover()
        assert store.get("s", "worker")["state"] == "running"
        assert store.finish(first, "completed", {"n": 1})
    finally:
        lease.release()
    second, lease2 = store.start("s", "worker", spec(tmp_path))
    try:
        assert not store.finish(first, "failed", {"late": True})
        assert store.get("s", "worker")["attempt"] == second.attempt_id
        assert store.get("s", "worker")["state"] == "running"
    finally:
        store.finish(second, "completed", {})
        lease2.release()


def test_abandoned_owner_is_recovered_but_history_is_retained(tmp_path):
    store = AgentRunStore()
    identity, lease = store.start("s", "worker", spec(tmp_path))
    lease.release()  # OS releases an identical lease on process exit.
    reopened = AgentRunStore()
    reopened.recover()
    assert reopened.get("s", "worker")["state"] == "interrupted"
    assert reopened.pending("s", "parent")[0]["kind"] == "completion"


def test_cross_session_write_scope_and_global_capacity(tmp_path):
    store = AgentRunStore()
    a, lock_a = store.start("s1", "a", spec(tmp_path, scope=["src"]), total_limit=2)
    try:
        with pytest.raises(AgentBusy, match="write_scope_busy"):
            store.start("s2", "b", spec(tmp_path, scope=["src/a.py"]))
        b, lock_b = store.start("s2", "b", spec(tmp_path, scope=["other"]), total_limit=2)
        try:
            with pytest.raises(AgentBusy, match="capacity"):
                store.start("s3", "c", spec(tmp_path), total_limit=2)
        finally:
            store.finish(b, "completed", {})
            lock_b.release()
    finally:
        store.finish(a, "completed", {})
        lock_a.release()


def test_durable_mail_dedupe_privacy_and_stale_recipient(tmp_path):
    store = AgentRunStore()
    a, la = store.start("s", "a", spec(tmp_path))
    b, lb = store.start("s", "b", spec(tmp_path))
    try:
        first = store.send("s", "b", "a", "finding", message_id="m1", expected_attempt=b.attempt_id)
        assert AgentRunStore().pending("s", "b")[0]["message_id"] == "m1"
        assert store.send("s", "b", "a", "finding", message_id="m1")["seq"] == first["seq"]
        with pytest.raises(ValueError, match="message_id_conflict"):
            store.send("s", "b", "a", "different", message_id="m1")
        with pytest.raises(ValueError, match="unknown_recipient"):
            store.send("other-session", "b", "parent", "cross-session")
        with pytest.raises(AgentBusy, match="stale_agent_attempt"):
            store.send("s", "b", "a", "stale", expected_attempt="old")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: store.send("s", "b", "a", str(n), message_id=f"parallel-{n}"), range(24)))
        assert len(store.pending("s", "b")) == 25
    finally:
        store.finish(a, "completed", {})
        store.finish(b, "completed", {})
        la.release()
        lb.release()


def test_mail_is_acknowledged_after_durable_transcript_and_not_duplicated(tmp_path):
    from engine.agent_mailbox import deliver_sync
    from session.message_store import MessageStore
    from session.hydrate import messages_from_transcript
    from engine.subagent_runner import _sidechain_path
    store = AgentRunStore()
    identity, lease = store.start("s", "worker", spec(tmp_path))
    try:
        store.send("s", "worker", "parent", "hello", message_id="m")
        messages = MessageStore()
        assert deliver_sync(messages, "s", "worker", identity.attempt_id) == 1
        saved = messages_from_transcript(_sidechain_path("s", "worker"), session_id="s")
        assert any("hello" in str(m.content) for m in saved)
        assert store.pending("s", "worker") == []
        store.send("s", "worker", "parent", "hello", message_id="m")
        assert deliver_sync(messages, "s", "worker", identity.attempt_id) == 0
        assert len(messages.items) == 1
    finally:
        store.finish(identity, "completed", {})
        lease.release()


def test_failed_transcript_write_does_not_acknowledge(tmp_path, monkeypatch):
    from engine.agent_mailbox import deliver_sync
    from session.message_store import MessageStore
    import importlib
    transcript = importlib.import_module("session.record_transcript")
    store = AgentRunStore()
    identity, lease = store.start("s", "worker", spec(tmp_path))
    store.send("s", "worker", "parent", "durable", message_id="m")
    def fail(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(transcript, "record_transcript_sync", fail)
    try:
        with pytest.raises(OSError):
            deliver_sync(MessageStore(), "s", "worker", identity.attempt_id)
        assert len(store.pending("s", "worker")) == 1
    finally:
        store.finish(identity, "failed", {})
        lease.release()


@pytest.mark.asyncio
async def test_child_contexts_do_not_mutate_parent_or_siblings(tmp_path):
    parent = ExecutionContext("s", str(tmp_path), model_request_id="parent", capabilities={"x": []})
    entered = asyncio.Event()
    async def child(name):
        with child_execution_context(tmp_path / name, "s", name):
            update_execution_context(model_request_id=name)
            get_execution_context().capabilities["x"].append(name)
            if name == "b":
                entered.set()
            await entered.wait()
            await asyncio.sleep(0)
            return get_execution_context().model_request_id, get_execution_context().capabilities
    with bind_workspace_context(parent):
        values = await asyncio.gather(child("a"), child("b"))
    assert values == [("a", {"x": ["a"]}), ("b", {"x": ["b"]})]
    assert parent.model_request_id == "parent" and parent.capabilities == {"x": []}


@pytest.mark.asyncio
async def test_background_parent_and_peer_message_lifecycle(tmp_path, monkeypatch):
    from engine.agent_runtime import control, shutdown
    from tools.agent_message_tool import AgentSendTool
    started = asyncio.Event()
    finish = asyncio.Event()
    captured = []
    async def child(self, agent_input, **kw):
        captured.append(current_agent.get())
        started.set()
        await finish.wait()
        return SubagentOutput(conclusion="done", stop_reason="finished")
    monkeypatch.setattr(AgentTool, "_run_subagent", child)
    tool = AgentTool(cwd=str(tmp_path), session_id="s")
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        try:
            handle = await tool.execute({"task_id": "a", "desc": "fixture"}, AbortController())
            await started.wait()
            identity = captured[0]
            assert handle.metadata["state"] == "running"
            sent = await AgentSendTool().execute({"agent_id": identity.agent_id, "text": "hello"}, AbortController())
            assert not sent.is_error
            repeated = await tool.execute({"task_id": "a", "desc": "fixture", "reuse_agent_id": identity.agent_id}, AbortController())
            assert repeated.is_error and "busy" in repeated.content
            token = current_agent.set(identity)
            try:
                peer = await AgentSendTool().execute({"agent_id": "parent", "text": "finding"}, AbortController())
                assert not peer.is_error
                denied = await control({"action": "interrupt", "agent_id": identity.agent_id}, AbortController())
                assert denied.is_error
            finally:
                current_agent.reset(token)
            finish.set()
            done = await control({"action": "wait", "agent_id": identity.agent_id}, AbortController())
            assert done.metadata["state"] == "completed"
            assert not AgentRunStore().get("s", identity.agent_id)["result"]["is_error"]
        finally:
            finish.set()
            await shutdown()


@pytest.mark.asyncio
async def test_workflow_parallel_preserves_root_context_and_budget(tmp_path):
    from tools.workflow_tool.workflow_tool import _ScriptRuntime
    from tools.base_tool import ToolResult
    from engine.shared_budget import current_budget, SharedBudget
    captured = []
    budget = SharedBudget(1.0, 1000)
    async def execute(payload, abort):
        captured.append((get_execution_context().session_id, current_budget.get(), payload["background"]))
        return ToolResult("fixture")
    script = _ScriptRuntime(agent_tool=SimpleNamespace(execute=execute), abort=AbortController(),
        loop=asyncio.get_running_loop(), run_short="test", max_agents=4, agent_timeout_s=2, meta={}, args={})
    token = current_budget.set(budget)
    try:
        with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
            await asyncio.to_thread(script._parallel, [lambda: script._agent("a"), lambda: script._agent("b")])
    finally:
        current_budget.reset(token)
    assert captured == [("s", budget, False), ("s", budget, False)]


def test_worktrees_snapshot_dirty_parent_and_never_collide(tmp_path):
    from engine.agent_workspaces import prepare
    root, git = repository(tmp_path)
    (root / "f.txt").write_text("user's uncommitted work\n")
    (root / "new.txt").write_text("untracked user work\n")
    before = git("status", "--porcelain")
    a = prepare(AgentIdentity("s", "agent-implement_backend-aaaa", "1"), spec(root, scope=["f.txt"], isolation="worktree"))
    (Path(a["worktree"]) / "sentinel").write_text("private")
    b = prepare(AgentIdentity("s", "agent-implement_backend-bbbb", "2"), spec(root, scope=["f.txt"], isolation="worktree"))
    assert a["worktree"] != b["worktree"]
    assert (Path(a["worktree"]) / "sentinel").read_text() == "private"
    assert (Path(b["worktree"]) / "f.txt").read_text() == "user's uncommitted work\n"
    assert (Path(b["worktree"]) / "new.txt").read_text() == "untracked user work\n"
    assert git("status", "--porcelain") == before


def test_worktree_retained_and_publication_preserves_index(tmp_path):
    from engine.agent_workspaces import prepare, collect, publish
    root, git = repository(tmp_path)
    (root / "f.txt").write_text("staged user work\n")
    git("add", "f.txt")
    index_before = git("ls-files", "--stage")
    artifact = prepare(AgentIdentity("s", "a", "1"), spec(root, scope=["f.txt"], isolation="worktree"))
    (Path(artifact["worktree"]) / "f.txt").write_text("worker changes\n")
    artifact = collect(artifact)
    assert (root / "f.txt").read_text() == "staged user work\n"
    applied = publish(artifact)
    assert (root / "f.txt").read_text() == "worker changes\n"
    assert git("ls-files", "--stage") == index_before
    assert Path(applied["worktree"]).is_dir()
    assert publish(applied) == applied


def test_publication_conflict_keeps_peer_write_and_git_state(tmp_path):
    from engine.agent_workspaces import prepare, collect, publish
    root, git = repository(tmp_path)
    artifact = prepare(AgentIdentity("s", "a", "1"), spec(root, scope=["f.txt"], isolation="worktree"))
    (Path(artifact["worktree"]) / "f.txt").write_text("worker\n")
    artifact = collect(artifact)
    (root / "f.txt").write_text("peer change\n")
    git("add", "f.txt")
    before = git("ls-files", "--stage")
    with pytest.raises(RuntimeError, match="publication_conflict"):
        publish(artifact)
    assert (root / "f.txt").read_text() == "peer change\n"
    assert git("ls-files", "--stage") == before
    assert git("ls-files", "-u") == b""


@pytest.mark.asyncio
async def test_failed_worker_retains_half_done_in_worktree(tmp_path, monkeypatch):
    from engine.agent_runtime import control
    root, git = repository(tmp_path)
    async def child(self, agent_input, **kw):
        (Path(kw["workspace_root"]) / "f.txt").write_text("half done\n")
        return SubagentOutput(conclusion="failed", is_error=True, stop_reason="error")
    monkeypatch.setattr(AgentTool, "_run_child", child)
    tool = AgentTool(cwd=str(root), session_id="s")
    tool.set_runtime_provider(lambda: SimpleNamespace(append_system_prompt=""))
    with bind_workspace_context(ExecutionContext("s", str(root))):
        output = await tool.execute({"task_id": "write", "desc": "fixture", "scope": ["f.txt"], "background": False}, AbortController())
    assert output.is_error
    row = AgentRunStore().list("s")[0]
    assert row["state"] == "failed"
    assert (Path(row["artifact"]["worktree"]) / "f.txt").read_text() == "half done\n"
    assert (root / "f.txt").read_text() == "base\n"


def test_tools_reach_parent_and_workers_without_spawn_privilege(tmp_path):
    from tools.catalog import build_default_registry, build_subagent_registry
    from engine.write_store import WriteStore
    root = build_default_registry(cwd=str(tmp_path))
    child = build_subagent_registry(cwd=str(tmp_path), tool_names=["agent_send", "agent_control", "Agent", "agent_apply"],
                                    write_store=WriteStore(tmp_path), agent_id="worker")
    assert root.get("agent_control") and root.get("agent_apply")
    assert child.get("agent_send") and child.get("agent_control")
    assert child.get("Agent") is None and child.get("agent_apply") is None


@pytest.mark.parametrize("managed", [False, True])
def test_read_evidence_isolation_ab(tmp_path, monkeypatch, managed):
    from tools.catalog import build_subagent_registry, shared_read_state
    from tools.fileio.read_state import ReadFileState, FileStateEntry
    monkeypatch.setenv("XEYO_AGENT_RUNTIME_V2", str(int(managed)))
    parent = ReadFileState()
    path = str(tmp_path / "f.txt")
    parent.set(path, FileStateEntry("parent observed", 1))
    registry = build_subagent_registry(cwd=str(tmp_path), tool_names=["Read", "Edit"], read_state=parent)
    worker = shared_read_state(registry)
    worker.set(path, FileStateEntry("worker observed", 2))
    assert parent.get(path).content == ("parent observed" if managed else "worker observed")


@pytest.mark.parametrize("managed", [False, True])
def test_duplicate_registration_ab(monkeypatch, managed):
    from engine.live_agents import register_live_agent, unregister_live_agent, is_live_agent, clear_all_for_tests
    monkeypatch.setenv("XEYO_AGENT_RUNTIME_V2", str(int(managed)))
    clear_all_for_tests()
    try:
        owner = register_live_agent("s", "a", AbortController())
        if managed:
            with pytest.raises(AgentBusy):
                register_live_agent("s", "a", AbortController())
            unregister_live_agent("s", "a", "late-old-attempt")
            assert is_live_agent("s", "a")
            unregister_live_agent("s", "a", owner)
        else:
            register_live_agent("s", "a", AbortController())
            unregister_live_agent("s", "a", owner)
            assert not is_live_agent("s", "a")
    finally:
        clear_all_for_tests()


@pytest.mark.parametrize("managed", [False, True])
def test_dependencies_survive_plan_and_gate_claim_ab(tmp_path, monkeypatch, managed):
    from coord.file_store import CoordFileStore
    from coord.planner import Planner
    monkeypatch.setenv("XEYO_AGENT_RUNTIME_V2", str(int(managed)))
    store = CoordFileStore(tmp_path)
    report = Planner(tmp_path, store).plan_round([
        {"task_id": "task_a", "title": "a", "scope": ["a"]},
        {"task_id": "task_b", "title": "b", "scope": ["b"], "deps": ["task_a"]},
    ])
    assert len(report["created"]) == 2
    assert bool(store.load_task("task_b").deps) == managed
    assert (store.claim_task("task_b", "w", "head") is None) == managed
    if managed:
        task = store.load_task("task_a")
        task.status = "completed"
        store._save_task(task)
        assert store.claim_task("task_b", "w", "head") is not None


def test_dependency_cycles_unknown_ids_and_duplicate_writes_are_rejected(tmp_path):
    from coord.file_store import CoordFileStore
    from coord.planner import Planner
    store = CoordFileStore(tmp_path)
    planner = Planner(tmp_path, store)
    result = planner.plan_round([
        {"task_id": "task_a", "scope": ["a"], "deps": ["task_b"]},
        {"task_id": "task_b", "scope": ["b"], "deps": ["task_a"]}])
    assert not result["created"] and store.list_tasks() == []
    assert "cyclic" in str(result)
    assert not planner.plan_round([{"scope": ["x"], "deps": ["absent"]}])["created"]


def test_stale_sender_cannot_message_a_new_attempt(tmp_path):
    store = AgentRunStore()
    first, lease = store.start("s", "a", spec(tmp_path))
    store.finish(first, "completed", {})
    lease.release()
    second, lease = store.start("s", "a", spec(tmp_path))
    try:
        with pytest.raises(AgentBusy, match="stale_sender"):
            store.send("s", "parent", "a", "late", sender_attempt=first.attempt_id)
        store.send("s", "parent", "a", "current", sender_attempt=second.attempt_id)
    finally:
        store.finish(second, "completed", {})
        lease.release()


@pytest.mark.asyncio
async def test_cancelled_prepare_keeps_owned_worktree_and_releases_attempt(tmp_path, monkeypatch):
    import threading
    from engine import agent_workspaces as ws
    root, _ = repository(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = ws.prepare
    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(ws, "prepare", delayed)
    tool = AgentTool(cwd=str(root), session_id="s")
    tool.set_runtime_provider(lambda: SimpleNamespace(append_system_prompt=""))
    with bind_workspace_context(ExecutionContext("s", str(root))):
        task = asyncio.create_task(tool.execute({"task_id": "write", "desc": "fixture", "scope": ["f.txt"], "background": False}, AbortController()))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(.03)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    row = AgentRunStore().list("s")[0]
    assert row["state"] == "cancelled" and Path(row["artifact"]["worktree"]).is_dir()
    lease = AgentRunStore().lease("s", row["agent"]).acquire()
    lease.release()


def test_publication_failure_rolls_back_and_recovers_journal(tmp_path, monkeypatch):
    import base64
    import hashlib
    from engine import agent_workspaces as ws
    root, git = repository(tmp_path)
    (root / "g.txt").write_text("old g\n")
    git("add", ".")
    git("commit", "-m", "two files")
    artifact = ws.prepare(AgentIdentity("s", "a", "1"), spec(root, scope=["f.txt", "g.txt"], isolation="worktree"))
    for name in ("f.txt", "g.txt"):
        (Path(artifact["worktree"]) / name).write_text("worker " + name)
    artifact = ws.collect(artifact)
    index = git("ls-files", "--stage")
    original = ws._atomic
    failed = False
    def fail_once(path, data):
        nonlocal failed
        if path == root / "g.txt" and not failed:
            failed = True
            raise OSError("disk full")
        original(path, data)
    monkeypatch.setattr(ws, "_atomic", fail_once)
    with pytest.raises(OSError, match="disk full"):
        ws.publish(artifact)
    assert (root / "f.txt").read_text() == "base\n"
    assert (root / "g.txt").read_text() == "old g\n"
    # A crashed publication already wrote f; explicit retry owns its remaining writes.
    receipt = {"state": "applying", "head": artifact["head"], "files": [
        {"path": name, "before": base64.b64encode((root / name).read_bytes()).decode(),
         "before_mode": (root / name).stat().st_mode,
         "after_sha256": hashlib.sha256((Path(artifact["worktree"]) / name).read_bytes()).hexdigest()}
        for name in ("f.txt", "g.txt")]}
    ws._save(Path(artifact["directory"]) / "publication.json", receipt)
    (root / "f.txt").write_bytes((Path(artifact["worktree"]) / "f.txt").read_bytes())
    ws.publish(artifact)
    assert (root / "g.txt").read_text() == "worker g.txt"
    assert git("ls-files", "--stage") == index
    assert ws.publish(artifact)["applied_head"] == artifact["head"]


@pytest.mark.asyncio
async def test_workflow_timeout_stops_thread_and_child(tmp_path, monkeypatch):
    from tools.workflow_tool.workflow_tool import WorkflowTool
    from tools.base_tool import ToolResult
    monkeypatch.setenv("XEYO_WORKFLOW_SCRIPT_TIMEOUT_S", ".05")
    stopped = asyncio.Event()
    async def execute(payload, abort):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    tool = WorkflowTool(cwd=str(tmp_path))
    monkeypatch.setattr(tool, "_build_agent_tool", lambda: SimpleNamespace(execute=execute))
    result = await asyncio.wait_for(tool.execute({"script": "return agent('work')", "meta": {"name": "w", "description": "d"}}, AbortController()), 3)
    assert result.is_error and stopped.is_set()
    result = await asyncio.wait_for(tool.execute({"script": "while True:\n    x = 1", "meta": {"name": "w", "description": "d"}}, AbortController()), 3)
    assert result.is_error
    result = await asyncio.wait_for(tool.execute({"script": "def work():\n    while True:\n        x = 1\nreturn parallel([work])", "meta": {"name": "w", "description": "d"}}, AbortController()), 3)
    assert result.is_error


@pytest.mark.asyncio
async def test_real_engine_parent_child_mail_and_wait(tmp_path, monkeypatch):
    from engine.query_engine import build_default_engine
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.catalog import build_default_registry
    from permissions.policy import set_permission_mode
    from engine.agent_runtime import shutdown
    child_requests = []
    class Model:
        last_usage = None
        parent_calls = 0
        child_calls = 0
        async def stream(self, messages, tools, abort):
            if current_agent.get():
                self.child_calls += 1
                child_requests.append(self.child_calls)
                if self.child_calls == 1:
                    assert any(t["name"] == "agent_send" for t in tools)
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("child-send", "agent_send", {"agent_id": "parent", "text": "peer finding", "message_id": "finding"}))
                else:
                    yield ModelChunk(kind="text_delta", text="child finished")
                return
            self.parent_calls += 1
            if self.parent_calls == 1:
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("spawn", "Agent", {"task_id": "read", "desc": "inspect fixture"}))
            elif self.parent_calls == 2:
                row = AgentRunStore().list("mail-e2e")[0]
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("wait", "agent_control", {"action": "wait", "agent_id": row["agent"], "attempt_id": row["attempt"], "timeout_s": 5}))
            else:
                assert "peer finding" in str(messages)
                assert 'completion' in str(messages)
                yield ModelChunk(kind="text_delta", text="parent finished")
    set_permission_mode("never")
    model = Model()
    monkeypatch.setattr("model.fake.FakeModelClient", lambda: model)
    engine = build_default_engine(cwd=str(tmp_path), session_id="mail-e2e", model_backend="fake", max_turns=6)
    try:
        events = [event async for event in engine.submit("inspect fixture")]
        assert model.parent_calls == 3 and child_requests == [1, 2]
        assert AgentRunStore().list("mail-e2e")[0]["state"] == "completed"
    finally:
        await shutdown()


def test_provider_request_state_is_private():
    from engine.agent_model import fork_runtime
    parent = SimpleNamespace(last_usage={"tokens": 1}, _usage_recorded_this_stream=True,
                             options={"nested": []}, context_limit=10000)
    runtime = SimpleNamespace(model_client=parent)
    a, b = fork_runtime(runtime).model_client, fork_runtime(runtime).model_client
    a.last_usage = {"tokens": 2}
    a.options["nested"].append("a")
    assert parent.last_usage == {"tokens": 1} and parent.options == {"nested": []}
    assert b.last_usage is None and b.options == {"nested": []}
    assert a.context_limit == 10000


def test_lease_excludes_a_second_process(tmp_path):
    import sys
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    script = "from pathlib import Path; from engine.agent_run_store import AgentRunStore; import sys; AgentRunStore(Path(sys.argv[1])).lease('s','a').acquire()"
    try:
        out = subprocess.run([sys.executable, "-c", script, str(store.directory)], capture_output=True, timeout=10)
        assert out.returncode != 0 and b"agent_busy" in out.stderr
    finally:
        store.finish(identity, "completed", {})
        lease.release()
    out = subprocess.run([sys.executable, "-c", script, str(store.directory)], capture_output=True, timeout=10)
    assert out.returncode == 0


def test_deleted_session_cannot_be_recreated_by_late_agent(tmp_path):
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path))
    try:
        with pytest.raises(AgentBusy, match="agents_stopping"):
            store.drop_session("s")
    finally:
        store.finish(identity, "completed", {"private": "result"})
        lease.release()
    store.drop_session("s")
    assert store.list("s") == [] and store.pending("s", "parent") == []
    with pytest.raises(AgentBusy, match="session_deleted"):
        store.start("s", "a", spec(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["readonly", "workspace_write"])
async def test_http_retry_uses_persisted_scope_and_session_permission(tmp_path, monkeypatch, profile):
    from server.routers import sessions
    from tools.base_tool import ToolResult
    store = AgentRunStore()
    original = {**spec(tmp_path, scope=["f.txt"], isolation="worktree"), "required_tools": ["Read"]}
    identity, lease = store.start("s", "agent-a", original)
    store.finish(identity, "failed", {})
    lease.release()
    captured = []
    async def execute(self, payload, abort):
        captured.append((payload, get_execution_context().permission_profile))
        return ToolResult("retried")
    monkeypatch.setattr(AgentTool, "execute", execute)
    tool = AgentTool(cwd=str(tmp_path), session_id="s")
    engine = SimpleNamespace(_tools={"Agent": tool}, permission_profile=profile)
    pool = SimpleNamespace(try_begin=lambda sid: 1, end=lambda *args: None, get_if_present=lambda sid: engine)
    monkeypatch.setattr(sessions, "_pool", pool)
    result = await sessions.session_agent_retry("s", "agent-a", None, None, None, None)
    if profile == "readonly":
        assert result["is_error"] and captured == []
        return
    assert result["status"] == "done"
    payload, preset = captured[0]
    assert payload["scope"] == ["f.txt"] and payload["required_tools"] == ["Read"]
    assert preset == profile and payload["background"] is False


@pytest.mark.asyncio
async def test_session_stop_settles_background_and_pool_pins_owner(tmp_path, monkeypatch):
    from engine.agent_runtime import session_active, shutdown
    from server.session_pool import SessionPool
    entered = asyncio.Event()
    async def child(self, *args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(AgentTool, "_run_subagent", child)
    pool = SessionPool(str(tmp_path), max_engines=1)
    engine = SimpleNamespace(interrupt=lambda: None, mutable_messages=[])
    pool._engines = {"s": (None, engine), "other": (None, engine)}
    pool._last_use = {"s": 0, "other": 1}
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        tool = AgentTool(cwd=str(tmp_path), session_id="s")
        handle = await tool.execute({"task_id": "a", "desc": "fixture"}, AbortController())
        await entered.wait()
        pool._evict_locked()
        assert "s" in pool._engines and "other" not in pool._engines
        assert pool.interrupt("s")
        await shutdown()
        assert not session_active("s")
        assert AgentRunStore().get("s", handle.metadata["agent_id"])["state"] == "cancelled"


def test_coord_long_ids_do_not_collide_or_erase_active_work(tmp_path):
    from coord.worktree import WorktreeManager, WorktreeError
    root, git = repository(tmp_path)
    manager = WorktreeManager(root)
    base = git("rev-parse", "HEAD").decode().strip()
    a = manager.create("task_implement_backend_same_prefix_a", base)
    (a.path / "sentinel").write_text("active work")
    b = manager.create("task_implement_backend_same_prefix_b", base)
    assert a.path != b.path and (a.path / "sentinel").read_text() == "active work"
    with pytest.raises(WorktreeError, match="worktree_resource_busy"):
        manager.create(a.task_id, base)
    assert (a.path / "sentinel").read_text() == "active work"


@pytest.mark.parametrize("mode", ["never", "always"])
@pytest.mark.asyncio
async def test_publication_through_real_registry_permission_path(tmp_path, mode):
    from engine.agent_workspaces import prepare, collect
    from tools.catalog import build_default_registry
    from msgtypes.message import ToolUse
    from permissions.policy import set_permission_mode
    root, _ = repository(tmp_path)
    store = AgentRunStore()
    run_spec = spec(root, scope=["f.txt"], isolation="worktree")
    identity, lease = store.start("s", "a", run_spec)
    artifact = prepare(identity, run_spec)
    (Path(artifact["worktree"]) / "f.txt").write_text("published\n")
    artifact = collect(artifact)
    store.artifact(identity, artifact)
    store.finish(identity, "completed", {})
    lease.release()
    registry = build_default_registry(cwd=str(root))
    request = ToolUse("apply", "agent_apply", {"agent_id": "a", "attempt_id": identity.attempt_id})
    set_permission_mode(mode)
    with bind_workspace_context(ExecutionContext("s", str(root))):
        if mode == "always":
            denied = await registry.run(request, AbortController())
            assert denied.is_error and (root / "f.txt").read_text() == "base\n"
        result = await registry.run(request, AbortController(), skip_ask=mode == "always")
    assert not result.is_error, result.content
    assert (root / "f.txt").read_text() == "published\n"


@pytest.mark.asyncio
async def test_readonly_cannot_resume_write_attempt_or_publish(tmp_path):
    from tools.agent_control_tool import AgentControlTool
    from permissions.policy import set_permission_mode, evaluate_policy
    from permissions.filesystem import PermissionDecision
    from permissions.runtime_preset import get_runtime_preset_store
    store = AgentRunStore()
    identity, lease = store.start("s", "a", spec(tmp_path, scope=["f.txt"]))
    store.finish(identity, "completed", {})
    lease.release()
    set_permission_mode("always")
    tool = AgentControlTool(cwd=str(tmp_path))
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        assert evaluate_policy("agent_control", {"action": "resume"}, cwd=str(tmp_path)).decision == PermissionDecision.ASK
        get_runtime_preset_store().set("s", "readonly")
        try:
            output = await tool.execute({"action": "resume", "agent_id": "a"}, AbortController())
            assert output.is_error and "Permission denied" in output.content
            status = await tool.execute({"action": "status", "agent_id": "a"}, AbortController())
            assert not status.is_error
        finally:
            get_runtime_preset_store().clear("s")


@pytest.mark.asyncio
async def test_default_engine_worker_writes_only_its_worktree_until_apply(tmp_path, monkeypatch):
    from engine.query_engine import build_default_engine
    from engine.agent_runtime import shutdown
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from permissions.policy import set_permission_mode
    root, git = repository(tmp_path)
    before_index = git("ls-files", "--stage")
    class Model:
        last_usage = None
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            if current_agent.get():
                if self.calls == 2:  # Snapshot at the parent's first Agent call.
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("read", "Read", {"file_path": "f.txt"}))
                elif self.calls == 3:
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("write", "Write", {"file_path": "f.txt", "content": "isolated change\n"}))
                else:
                    yield ModelChunk(kind="text_delta", text="worker finished")
                return
            if self.calls == 1:
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("spawn", "Agent", {"task_id": "write", "desc": "change f.txt", "scope": ["f.txt"]}))
            elif self.calls in (2, 3):
                row = AgentRunStore().list("write-e2e")[0]
                request = {"agent_id": row["agent"], "attempt_id": row["attempt"]}
                if self.calls == 2:
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("wait", "agent_control", {**request, "action": "wait", "timeout_s": 5}))
                else:
                    assert row["state"] == "completed", row["result"]
                    assert (root / "f.txt").read_text() == "base\n"
                    assert (Path(row["artifact"]["worktree"]) / "f.txt").read_text() == "isolated change\n"
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("publish", "agent_apply", request))
            else:
                assert (root / "f.txt").read_text() == "isolated change\n"
                yield ModelChunk(kind="text_delta", text="parent finished")
    model = Model()
    monkeypatch.setattr("model.fake.FakeModelClient", lambda: model)
    set_permission_mode("never")
    engine = build_default_engine(cwd=str(root), session_id="write-e2e", model_backend="fake", max_turns=6)
    try:
        _ = [event async for event in engine.submit("change f.txt in a worker then publish")]
        assert model.calls == 4
        assert git("ls-files", "--stage") == before_index
    finally:
        await shutdown()
