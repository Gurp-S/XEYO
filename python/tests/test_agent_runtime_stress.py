"""Offline concurrent/fault tests. Barriers identify the exact crash/race window."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import threading
import time

import pytest

from engine.abort import AbortController
from engine.agent_identity import AgentBusy, current_agent
from engine.agent_run_store import AgentRunStore
from engine.workspace_context import ExecutionContext, bind_workspace_context
from session.message_store import MessageStore
from tests.test_agent_runtime_v2 import repository, spec


@pytest.fixture(autouse=True)
def managed(monkeypatch):
    monkeypatch.setenv("XEYO_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("XEYO_DOCKER_CONTAINER", "")


def report(record_property, **metrics):
    for key, value in metrics.items():
        record_property(key, json.dumps(value))


async def eventually(predicate, timeout=10):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.005)


@pytest.mark.parametrize("seed", [7, 41, 103])
def test_parallel_mail_conservation(tmp_path, record_property, seed):
    """16 receivers / 8 sessions, 768 unique messages with concurrent replays."""
    from engine.agent_mailbox import deliver_sync, _message
    from engine.subagent_runner import _sidechain_path
    from session.hydrate import messages_from_transcript
    store = AgentRunStore()
    owners = [store.start(f"s{s}", f"a{a}", spec(tmp_path)) for s in range(8) for a in range(2)]
    by_id = {(i.session_id, i.agent_id): i for i, _ in owners}
    messages = {(i.session_id, i.agent_id): MessageStore() for i, _ in owners}
    rng = random.Random(seed)
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=16) as threads:
            for wave in range(3):
                sends = [(i, n) for i, _ in owners for n in range(16)] * 2
                rng.shuffle(sends)
                def send(item):
                    identity, n = item
                    peer = by_id[identity.session_id, "a1" if identity.agent_id == "a0" else "a0"]
                    return store.send(identity.session_id, identity.agent_id, peer.agent_id if n % 2 else "parent",
                        f"{identity.session_id}/{identity.agent_id}/{wave}/{n}",
                        message_id=f"{identity.agent_id}-{wave}-{n}", expected_attempt=identity.attempt_id,
                        sender_attempt=peer.attempt_id if n % 2 else "")
                receipts = list(threads.map(send, sends))
                assert len({r["seq"] for r in receipts}) == 256
                jobs = [("deliver", i, 0) for i, _ in owners]
                jobs += [("remove", i, n) for i, _ in owners for n in range(0, 16, 4)]
                rng.shuffle(jobs)
                def consume(job):
                    action, i, n = job
                    if action == "remove":
                        return store.remove_message(i.session_id, i.agent_id, message_id=f"{i.agent_id}-{wave}-{n}")
                    return deliver_sync(messages[i.session_id, i.agent_id], i.session_id, i.agent_id, i.attempt_id)
                list(threads.map(consume, jobs))
            totals = {"delivered": 0, "cancelled": 0}
            for i, _ in owners:
                assert not store.pending(i.session_id, i.agent_id)
                with store.connection() as db:
                    rows = [dict(r) for r in db.execute("SELECT * FROM mailbox WHERE session=? AND recipient=?", (i.session_id, i.agent_id))]
                assert len(rows) == 48
                assert all(r["state"] in totals for r in rows)
                for r in rows:
                    totals[r["state"]] += 1
                expected = {_message(r).id for r in rows if r["state"] == "delivered"}
                saved = messages_from_transcript(_sidechain_path(i.session_id, i.agent_id), session_id=i.session_id)
                assert len(saved) == len(expected)
                assert {m.id for m in saved} == expected == {m.id for m in messages[i.session_id, i.agent_id].items}
                assert all(r["text"].startswith(i.session_id + "/" + i.agent_id + "/") for r in rows)
        report(record_property, seed=seed, sessions=8, receivers=16, unique_messages=768,
               send_requests=1536, peer_messages=384, parent_messages=384,
               **totals, elapsed_s=round(time.monotonic() - started, 3))
    finally:
        for i, lease in owners:
            store.finish(i, "completed", {})
            lease.release()


@pytest.mark.asyncio
async def test_runtime_cancel_retry_waves(tmp_path, monkeypatch, record_property):
    from engine import agent_runtime as runtime
    from tools.agent_tool import AgentTool
    from tools.base_tool import ToolResult
    store = AgentRunStore()
    entered = set()
    release = asyncio.Event()
    async def child(self, payload, abort):
        i = current_agent.get()
        entered.add((i.session_id, i.agent_id, i.attempt_id))
        await release.wait()
        abort.raise_if_aborted()
        return ToolResult(i.session_id + "/" + i.agent_id)
    monkeypatch.setattr(AgentTool, "_execute_legacy", child)
    async def start(s, a, expected=None):
        sid = f"s{s}"
        with bind_workspace_context(ExecutionContext(sid, str(tmp_path))):
            return await runtime.dispatch(AgentTool(cwd=str(tmp_path), session_id=sid),
                {"desc": "stress", "task_id": "task", "reuse_agent_id": f"a{a}",
                 **({"reuse_attempt_id": expected} if expected else {})}, AbortController())
    started = time.monotonic()
    try:
        for wave in range(3):
            entered.clear()
            release = asyncio.Event()
            results = await asyncio.gather(*(start(s, a) for s in range(8) for a in range(4)))
            assert all(not r.is_error for r in results), [r.content for r in results if r.is_error]
            await eventually(lambda: len(entered) == 32)
            runs = list(runtime._running.values())
            assert len(runs) == 32
            overflow = await start(8, 0)
            assert "agent_capacity_exhausted" in overflow.content
            cancelled = runs[::2]
            for r in cancelled:
                for _ in range(3):
                    assert runtime.cancel(r.identity.session_id, r.identity.agent_id, r.identity.attempt_id)
            await asyncio.gather(*(r.task for r in cancelled), return_exceptions=True)
            assert all(store.get(r.identity.session_id, r.identity.agent_id)["state"] == "cancelled" for r in cancelled)
            retried = await asyncio.gather(*(start(int(r.identity.session_id[1:]), int(r.identity.agent_id[1:]), r.identity.attempt_id) for r in cancelled))
            assert all(not r.is_error for r in retried)
            await eventually(lambda: len(entered) == 48)
            for r in cancelled:
                assert not runtime.cancel(r.identity.session_id, r.identity.agent_id, r.identity.attempt_id)
            release.set()
            await asyncio.gather(*(r.task for r in tuple(runtime._running.values())))
            assert not runtime._running
            assert all(row["state"] == "completed" for s in range(8) for row in store.list(f"s{s}"))
        with store.connection() as db:
            counts = dict(db.execute("SELECT state,count(*) FROM attempts GROUP BY state").fetchall())
            completions = db.execute("SELECT count(*) FROM mailbox WHERE kind='completion'").fetchone()[0]
        assert counts == {"cancelled": 48, "completed": 96} and completions == 144
        report(record_property, sessions=8, peak_running=32, waves=3, attempts=144, completions=completions,
               cancelled=48, stale_cancels_rejected=48, overflow_rejected=3, elapsed_s=round(time.monotonic() - started, 3))
    finally:
        release.set()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_shutdown_drains_inflight_admission(tmp_path, monkeypatch):
    from engine import agent_runtime as runtime
    from tools.agent_tool import AgentTool
    from tools.base_tool import ToolResult
    gate, entered = threading.Event(), threading.Event()
    original = AgentRunStore.start
    def start(self, *a, **kw):
        entered.set()
        assert gate.wait(10)
        return original(self, *a, **kw)
    monkeypatch.setattr(AgentRunStore, "start", start)
    async def child(self, payload, abort):
        abort.raise_if_aborted()
        return ToolResult("done")
    monkeypatch.setattr(AgentTool, "_execute_legacy", child)
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        task = asyncio.create_task(runtime.dispatch(AgentTool(cwd=str(tmp_path), session_id="s"), {"desc": "race"}, AbortController()))
    shutdown = None
    try:
        await eventually(entered.is_set)
        shutdown = asyncio.create_task(runtime.shutdown())
        await asyncio.sleep(.05)
        assert not shutdown.done(), "shutdown returned with a live admission thread"
        gate.set()
        await asyncio.wait_for(shutdown, 10)
        await asyncio.gather(task, return_exceptions=True)
        assert not runtime.session_active("s")
        assert all(r["state"] == "cancelled" for r in AgentRunStore().list("s"))
    finally:
        gate.set()
        await asyncio.gather(task, *([shutdown] if shutdown else []), return_exceptions=True)
        await runtime.shutdown()


def test_session_delete_cannot_overtake_claimed_parent_delivery(tmp_path, monkeypatch):
    from engine.agent_mailbox import deliver_sync
    transcript = importlib.import_module("session.record_transcript")
    store = AgentRunStore()
    i, lease = store.start("s", "a", spec(tmp_path))
    store.finish(i, "completed", {})
    lease.release()
    entered, release = threading.Event(), threading.Event()
    original = transcript.record_transcript_sync
    def write(*a, **kw):
        entered.set()
        assert release.wait(10)
        return original(*a, **kw)
    monkeypatch.setattr(transcript, "record_transcript_sync", write)
    with ThreadPoolExecutor(max_workers=1) as threads:
        delivery = threads.submit(deliver_sync, MessageStore(), "s", "parent")
        try:
            assert entered.wait(5)
            with pytest.raises(AgentBusy, match="delivery_busy"):
                store.drop_session("s")
        finally:
            release.set()
            delivery.result(timeout=10)
    store.drop_session("s")
    with pytest.raises(AgentBusy, match="session_deleted"):
        deliver_sync(MessageStore(), "s", "parent")


@pytest.mark.parametrize("point", ["claimed", "persisted", "acknowledged"])
def test_process_crash_mail_delivery_replay(tmp_path, point, record_property):
    from engine.agent_mailbox import deliver_sync, _message
    from engine.subagent_runner import _sidechain_path
    from session.hydrate import messages_from_transcript
    store = AgentRunStore()
    i, lease = store.start("s", "a", spec(tmp_path))
    for n in range(40):
        store.send("s", "a", "parent", str(n), message_id=f"m{n}")
    store.finish(i, "failed", {})
    lease.release()
    script = '''
import os, sys
from engine.agent_run_store import AgentRunStore
from engine.agent_mailbox import deliver_sync
from session.message_store import MessageStore
store = AgentRunStore()
i, lease = store.start('s', 'a', store.get('s', 'a')['spec'])
point = sys.argv[1]
if point == 'claimed':
    store.claim_messages('s', 'a', attempt=i.attempt_id)
    os._exit(23)
original = AgentRunStore.acknowledge
def ack(self, *args, **kwargs):
    if point == 'acknowledged': original(self, *args, **kwargs)
    os._exit(23)
AgentRunStore.acknowledge = ack
deliver_sync(MessageStore(), 's', 'a', i.attempt_id)
'''
    exited = subprocess.run([sys.executable, "-c", script, point], capture_output=True, timeout=20)
    assert exited.returncode == 23, exited.stderr.decode(errors="replace")
    with ThreadPoolExecutor(max_workers=8) as threads:
        list(threads.map(lambda _: store.recover(), range(16)))
    row = store.get("s", "a")
    assert row["state"] == "interrupted"
    i, lease = store.start("s", "a", row["spec"])
    try:
        saved = messages_from_transcript(_sidechain_path("s", "a"), session_id="s")
        messages = MessageStore(saved)
        while deliver_sync(messages, "s", "a", i.attempt_id):
            pass
        saved = messages_from_transcript(_sidechain_path("s", "a"), session_id="s")
        assert len(saved) == len({m.id for m in saved}) == 40
        with store.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM mailbox WHERE recipient='a'")]
            completions = db.execute("SELECT count(*) FROM mailbox WHERE kind='completion'").fetchone()[0]
        assert completions == 2
        assert all(r["state"] == "delivered" for r in rows)
        assert {m.id for m in saved} == {_message(r).id for r in rows}
        report(record_property, crash_point=point, messages=40, recovery_contenders=16, duplicate_transcript_rows=0)
    finally:
        store.finish(i, "completed", {})
        lease.release()


@pytest.mark.parametrize("point", ["first_file", "receipt"])
def test_process_crash_during_publication(tmp_path, point, record_property):
    from engine import agent_workspaces as ws
    root, git = repository(tmp_path)
    (root / "g.txt").write_text("second base")
    git("add", "g.txt")
    git("commit", "-m", "second")
    index = (root / ".git" / "index").read_bytes()
    store = AgentRunStore()
    run_spec = spec(root, scope=["f.txt", "g.txt"], isolation="worktree")
    i, lease = store.start("s", "a", run_spec)
    artifact = ws.prepare(i, run_spec)
    for name in ("f.txt", "g.txt"):
        (Path(artifact["worktree"]) / name).write_text("published " + name)
    artifact = ws.collect(artifact)
    store.artifact(i, artifact)
    store.finish(i, "completed", {})
    lease.release()
    script = '''
import os, sys
from engine import agent_workspaces as ws
from engine.agent_run_store import AgentRunStore
store = AgentRunStore()
lease = store.lease('s', 'a').acquire()
artifact = store.get('s', 'a')['artifact']
original = ws._atomic
def atomic(path, data):
    original(path, data)
    if sys.argv[1] == 'first_file' and path.name == 'f.txt': os._exit(23)
    if sys.argv[1] == 'receipt' and path.name == 'publication.json' and b'"applied"' in data: os._exit(23)
ws._atomic = atomic
ws.publish(artifact)
raise RuntimeError('fault hook did not fire')
'''
    exited = subprocess.run([sys.executable, "-c", script, point], capture_output=True, timeout=30)
    assert exited.returncode == 23, exited.stderr.decode(errors="replace")
    result = ws.publish(artifact)
    assert ws.publish(result)["applied_head"] == result["head"]
    assert all((root / name).read_text() == "published " + name for name in ("f.txt", "g.txt"))
    assert (root / ".git" / "index").read_bytes() == index
    report(record_property, crash_point=point, published_files=2, parent_index_preserved=True)


def test_live_workspace_owner_is_not_stolen_after_heartbeat_delay(tmp_path):
    from engine.workspace_lock import WorkspaceLock, LeaseBusyError
    first = WorkspaceLock(tmp_path, owner="live", ttl_seconds=30)
    lease = first.acquire()
    try:
        first._heartbeat_stop.set()
        first._heartbeat_thread.join(timeout=2)
        os.utime(first._heartbeat_path(lease.lease_id), (1, 1))
        second = WorkspaceLock(tmp_path, owner="contender", ttl_seconds=30)
        try:
            with pytest.raises(LeaseBusyError):
                second.acquire()
            assert not second.reclaim_stale_if_expired()
            assert not first.reclaim_stale_if_expired()
            assert first._read_lease().lease_id == lease.lease_id
        finally:
            second.release()
    finally:
        first.release()


@pytest.mark.parametrize("mode,admitted", [("identity", 1), ("scope", 1), ("quota", 4)])
def test_competing_processes_killed_owner_recovery(tmp_path, mode, admitted, record_property):
    script = '''
import json, sys
from engine.agent_run_store import AgentRunStore
from engine.agent_identity import AgentBusy
store = AgentRunStore()
print('ready', flush=True)
sys.stdin.readline()
mode, number, cwd = sys.argv[1:]
sid = 'same' if mode == 'identity' else 's' + number
spec = dict(cwd=cwd, task_id='task', desc='process', isolation='shared', scope=['src'] if mode == 'scope' else [])
try:
    i, lease = store.start(sid, 'worker', spec, total_limit=4)
except AgentBusy as exc:
    print(json.dumps(dict(error=str(exc))), flush=True)
else:
    print(json.dumps(dict(session=sid, attempt=i.attempt_id)), flush=True)
    sys.stdin.readline()
'''
    processes = [subprocess.Popen([sys.executable, "-u", "-c", script, mode, str(n), str(tmp_path)],
                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) for n in range(8)]
    try:
        with ThreadPoolExecutor(max_workers=8) as readers:
            assert list(readers.map(lambda p: p.stdout.readline().strip(), processes)) == ["ready"] * 8
            for process in processes:
                process.stdin.write("go\n")
                process.stdin.flush()
            results = list(readers.map(lambda p: json.loads(p.stdout.readline()), processes))
        assert sum("attempt" in r for r in results) == admitted, results
        for process, receipt in zip(processes, results):
            if "attempt" in receipt:
                process.kill()
            process.wait(timeout=10)
        store = AgentRunStore()
        with ThreadPoolExecutor(max_workers=8) as threads:
            list(threads.map(lambda _: store.recover(), range(16)))
        with store.connection() as db:
            states = [r[0] for r in db.execute("SELECT state FROM agents")]
            completions = db.execute("SELECT count(*) FROM mailbox WHERE kind='completion'").fetchone()[0]
        assert states == ["interrupted"] * admitted and completions == admitted
        for receipt in results:
            if "attempt" in receipt:
                row = store.get(receipt["session"], "worker")
                i, lease = store.start(receipt["session"], "worker", row["spec"], expected_attempt=receipt["attempt"])
                store.finish(i, "completed", {})
                lease.release()
        report(record_property, mode=mode, contenders=8, admitted=admitted, forcibly_killed=admitted,
               recovery_contenders=16, duplicate_completions=0)
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=10)


@pytest.mark.asyncio
async def test_http_parallel_worktrees_cancel_and_messages(tmp_path, monkeypatch, record_property):
    from fastapi import FastAPI
    import httpx
    from engine import agent_runtime as runtime
    from engine.query_engine import build_default_engine
    from engine.subagent_runner import _sidechain_path
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from server.routers import sessions
    from server.session_pool import SessionPool
    from session.hydrate import messages_from_transcript
    root, git = repository(tmp_path)
    parent_index = (root / ".git" / "index").read_bytes()
    store = AgentRunStore()
    entered = set()
    release = asyncio.Event()
    seen = {}
    class Model:
        calls = 0
        last_usage = None
        async def stream(self, messages, tools, abort):
            i = current_agent.get()
            assert i is not None
            self.calls += 1
            if self.calls == 1:
                entered.add(i.session_id)
                await release.wait()
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("read", "Read", {"file_path": "f.txt"}))
            elif self.calls == 2:
                seen[i.session_id] = str(messages)
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("write", "Write", {"file_path": "f.txt", "content": "private " + i.session_id}))
            else:
                yield ModelChunk(kind="text_delta", text="done")
    monkeypatch.setattr("model.fake.FakeModelClient", Model)
    engines = {}
    prior = {}
    for n in range(6):
        sid = f"session{n}"
        i, lease = store.start(sid, "worker", spec(root, scope=["f.txt"], isolation="worktree"))
        store.finish(i, "failed", {})
        lease.release()
        prior[sid] = i.attempt_id
        engines[sid] = build_default_engine(cwd=str(root), session_id=sid, model_backend="fake", max_turns=5)
    pool = SessionPool(cwd=str(root))
    monkeypatch.setattr(pool, "get_if_present", engines.get)
    monkeypatch.setattr(sessions, "_pool", pool)
    app = FastAPI()
    app.include_router(sessions.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        tasks = {sid: asyncio.create_task(client.post(f"/v1/sessions/{sid}/agents/worker/retry", json={"attempt_id": old})) for sid, old in prior.items()}
        try:
            await eventually(lambda: len(entered) == 6, timeout=25)
            duplicate = await client.post("/v1/sessions/session0/agents/worker/retry", json={"attempt_id": prior["session0"]})
            assert duplicate.status_code == 409
            stale = await client.post("/v1/sessions/session0/agents/worker/cancel", json={"attempt_id": prior["session0"]})
            assert stale.status_code == 409
            async def send(sid):
                response = await client.post(f"/v1/sessions/{sid}/agents/worker/inbox", json={"text": "only-" + sid, "message_id": "same-id"})
                assert response.status_code == 200, response.text
            await asyncio.gather(*(send(sid) for sid in engines for _ in range(3)))
            for sid in ("session0", "session1"):
                response = await client.post(f"/v1/sessions/{sid}/agents/worker/cancel", json={"attempt_id": store.get(sid, "worker")["attempt"]})
                assert response.status_code == 200
            cancelled = await asyncio.gather(tasks["session0"], tasks["session1"], return_exceptions=True)
            assert all(isinstance(r, httpx.Response) and r.status_code == 200 and r.json()["is_error"] for r in cancelled), cancelled
            for sid in ("session0", "session1"):
                tasks[sid] = asyncio.create_task(client.post(f"/v1/sessions/{sid}/agents/worker/retry", json={"attempt_id": store.get(sid, "worker")["attempt"]}))
            release.set()
            responses = await asyncio.gather(*tasks.values())
            assert all(r.status_code == 200 and not r.json()["is_error"] for r in responses), [r.text for r in responses]
            artifacts = []
            for sid in engines:
                row = store.get(sid, "worker")
                assert row["state"] == "completed"
                artifacts.append(row["artifact"]["worktree"])
                assert (Path(row["artifact"]["worktree"]) / "f.txt").read_text() == "private " + sid
                assert "only-" + sid in seen[sid]
                assert all("only-" + other not in seen[sid] for other in engines if other != sid)
                saved = messages_from_transcript(_sidechain_path(sid, "worker"), session_id=sid)
                assert sum("only-" + sid in str(m.content) for m in saved) == 1
                assert not store.pending(sid, "worker")
                assert not pool.is_busy(sid) and not pool.batch_is_active(sid)
            assert len(set(artifacts)) == 6
            assert (root / "f.txt").read_text() == "base\n"
            assert (root / ".git" / "index").read_bytes() == parent_index
            report(record_property, http_sessions=6, worktrees=6, cancelled_and_retried=2,
                   message_requests=18, unique_messages=6, cross_session_leaks=0, parent_index_preserved=True)
        finally:
            release.set()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            await runtime.shutdown()


@pytest.mark.asyncio
async def test_parallel_parent_loops_receive_only_their_children(tmp_path, monkeypatch, record_property):
    from engine.query_engine import build_default_engine
    from engine.workspace_context import get_execution_context
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from permissions.policy import set_permission_mode
    from engine.agent_runtime import shutdown
    root, _ = repository(tmp_path)
    reached = set()
    all_children = asyncio.Event()
    observed = {}
    peer_observed = set()
    sent_peers = set()
    peer_sends_done = asyncio.Event()
    class Model:
        last_usage = None
        parent_calls = 0
        child_calls = 0
        async def stream(self, messages, tools, abort):
            sid = get_execution_context().session_id
            if current_agent.get():
                identity = current_agent.get()
                self.child_calls += 1
                if self.child_calls == 1:
                    reached.add((sid, identity.agent_id))
                    if len(reached) == 16:
                        all_children.set()
                    await asyncio.wait_for(all_children.wait(), 15)
                    peer = next(r for r in AgentRunStore().list(sid) if r["agent"] != identity.agent_id)
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("peer-send", "agent_send",
                        {"agent_id": peer["agent"], "attempt_id": peer["attempt"],
                         "text": "peer-for-" + sid + "/" + peer["agent"], "message_id": "peer"}))
                elif self.child_calls == 2:
                    sent_peers.add((sid, identity.agent_id))
                    if len(sent_peers) == 16:
                        peer_sends_done.set()
                    await asyncio.wait_for(peer_sends_done.wait(), 15)
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("parent-send", "agent_send",
                        {"agent_id": "parent", "text": "finding-for-" + sid, "message_id": "same-id"}))
                else:
                    assert "peer-for-" + sid + "/" + identity.agent_id in str(messages)
                    peer_observed.add((sid, identity.agent_id))
                    yield ModelChunk(kind="text_delta", text="child done")
                return
            self.parent_calls += 1
            if self.parent_calls == 1:
                for n in range(2):
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"spawn{n}", "Agent", {"task_id": f"read{n}", "desc": "inspect"}))
            elif self.parent_calls == 2:
                rows = AgentRunStore().list(sid)
                assert rows, str(messages)
                assert len(rows) == 2
                for n, row in enumerate(rows):
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"wait{n}", "agent_control",
                        {"action": "wait", "agent_id": row["agent"], "attempt_id": row["attempt"], "timeout_s": 20}))
            else:
                observed[sid] = str(messages)
                yield ModelChunk(kind="text_delta", text="parent done")
    monkeypatch.setattr("model.fake.FakeModelClient", Model)
    set_permission_mode("never")
    engines = [build_default_engine(cwd=str(root), session_id=f"chat{n}", model_backend="fake", max_turns=6) for n in range(8)]
    async def submit(engine):
        return [event async for event in engine.submit("inspect")]
    try:
        results = await asyncio.wait_for(asyncio.gather(*(submit(e) for e in engines), return_exceptions=True), 30)
        assert not [r for r in results if isinstance(r, BaseException)]
        assert len(observed) == 8
        for sid, contents in observed.items():
            assert "finding-for-" + sid in contents and "completion" in contents
            assert all("finding-for-" + other not in contents for other in observed if other != sid)
            assert all(row["state"] == "completed" for row in AgentRunStore().list(sid))
            assert not AgentRunStore().pending(sid, "parent")
        assert len(peer_observed) == 16
        report(record_property, parent_loops=8, concurrent_children=16, upward_messages=16,
               peer_messages_observed=16, completions=16, cross_session_leaks=0)
    finally:
        all_children.set()
        peer_sends_done.set()
        await shutdown()


@pytest.mark.asyncio
async def test_repeated_caller_cancel_waits_for_owned_settlement(tmp_path, monkeypatch):
    from engine import agent_runtime as runtime
    from engine.agent_io import owned_io
    from tools.agent_tool import AgentTool
    entered, settling, release = asyncio.Event(), threading.Event(), threading.Event()
    def blocking_cleanup():
        settling.set()
        assert release.wait(10)
    async def child(self, payload, abort):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await owned_io(blocking_cleanup)
    monkeypatch.setattr(AgentTool, "_execute_legacy", child)
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        task = asyncio.create_task(runtime.dispatch(AgentTool(cwd=str(tmp_path), session_id="s"),
                                  {"desc": "cleanup", "background": False}, AbortController()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await eventually(settling.is_set)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(.01)
        assert not task.done()
        row = AgentRunStore().list("s")[0]
        with pytest.raises(AgentBusy):
            AgentRunStore().lease("s", row["agent"]).acquire()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not runtime.session_active("s")
        assert AgentRunStore().get("s", row["agent"])["state"] == "cancelled"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancellation_still_drains_and_rejects_new_admission(tmp_path, monkeypatch):
    from engine import agent_runtime as runtime
    from engine.agent_io import owned_io
    from tools.agent_tool import AgentTool
    entered, settling, release = asyncio.Event(), threading.Event(), threading.Event()
    async def child(self, payload, abort):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            def cleanup():
                settling.set()
                assert release.wait(10)
            await owned_io(cleanup)
    monkeypatch.setattr(AgentTool, "_execute_legacy", child)
    tool = AgentTool(cwd=str(tmp_path), session_id="s")
    with bind_workspace_context(ExecutionContext("s", str(tmp_path))):
        await runtime.dispatch(tool, {"desc": "shutdown"}, AbortController())
        await asyncio.wait_for(entered.wait(), 5)
        stopping = asyncio.create_task(runtime.shutdown())
        try:
            await eventually(settling.is_set)
            stopping.cancel()
            response = await runtime.dispatch(tool, {"desc": "late"}, AbortController())
            assert "agent_runtime_stopping" in response.content
            assert not stopping.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await stopping
            assert not runtime.session_active("s")
        finally:
            release.set()
            await asyncio.gather(stopping, return_exceptions=True)
            await runtime.shutdown()
