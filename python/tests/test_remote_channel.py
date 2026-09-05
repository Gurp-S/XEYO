"""远程 channel：final-only runner、认证与 job 存储。"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from channels.auth import remote_enabled, verify_remote_token
from channels.jobs import JobStore
from channels.runner import FinalOnlyRunner, run_final_only
from msgtypes.events import (
	AssistantDelta,
	FinalEvent,
	PermissionPendingEvent,
	PermissionResolvedEvent,
	ResultEvent,
	StoppedEvent,
	TaskStateEvent,
	ToolCallEvent,
	ToolResultEvent,
)
from server.session_pool import ModelConfig


class _FakeEngine:
	def __init__(self, events: list[Any]) -> None:
		self._events = events

	async def submit(self, _text: str) -> AsyncIterator[Any]:
		for ev in self._events:
			yield ev

	def interrupt(self) -> None:
		pass


class _FakePool:
	"""final-only 测试用的最小 SessionPool 替身。"""

	def __init__(self, events: list[Any]) -> None:
		self._events = events
		self._busy = False
		self.ended = False
		self.lease_id = 1

	def try_begin(self, _session_id: str) -> int | None:
		if self._busy:
			return None
		self._busy = True
		return self.lease_id

	def end(self, _session_id: str, lease_id: int | None = None) -> None:
		if lease_id is not None and lease_id != self.lease_id:
			return
		self._busy = False
		self.ended = True

	def get_or_create(self, *_a: Any, **_k: Any) -> _FakeEngine:
		return _FakeEngine(self._events)

	def take_pending_interrupt(self, _session_id: str) -> bool:
		return False


_CFG = ModelConfig(
	provider="deepseek",
	api_key="k",
	base_url="https://example.com/v1",
	model="m",
)


@pytest.mark.asyncio
async def test_run_final_only_ignores_deltas_and_tools():
	events = [
		AssistantDelta(text="thinking..."),
		ToolCallEvent(name="Bash", input={"cmd": "ls"}),
		ToolResultEvent(name="Bash", output="ok"),
		AssistantDelta(text="more mid"),
		FinalEvent(text="THE_FINAL"),
		ResultEvent(subtype="success", result="THE_FINAL"),
	]
	pool = _FakePool(events)
	out = await run_final_only(pool, session_id="remote:t", text="hi", cfg=_CFG)  # type: ignore[arg-type]
	assert out == "THE_FINAL"
	assert pool.ended is True


@pytest.mark.asyncio
async def test_run_final_only_mirrors_deltas_locally():
	events = [
		AssistantDelta(text="hel"),
		AssistantDelta(text="lo"),
		FinalEvent(text="THE_FINAL"),
		ResultEvent(subtype="success", result="THE_FINAL"),
	]
	pool = _FakePool(events)
	chunks: list[str] = []

	def on_delta(chunk: str, session_id: str) -> None:
		chunks.append(f"{session_id}:{chunk}")

	out = await run_final_only(
		pool,  # type: ignore[arg-type]
		session_id="filehelper:default",
		text="hi",
		cfg=_CFG,
		on_delta=on_delta,
	)
	assert out == "THE_FINAL"
	assert chunks == ["filehelper:default:hel", "filehelper:default:lo"]


@pytest.mark.asyncio
async def test_run_final_only_mirrors_tools_locally():
	events = [
		AssistantDelta(text="先想想"),
		ToolCallEvent(name="Screenshot", input={"monitor": 1}),
		ToolResultEvent(name="Screenshot", output="saved"),
		FinalEvent(text="好了"),
		ResultEvent(subtype="success", result="好了"),
	]
	pool = _FakePool(events)
	calls: list[Any] = []

	def on_tool_call(name: str, _input: dict, session_id: str) -> None:
		calls.append(("call", name, session_id))

	def on_tool_result(
		name: str, output: str, is_error: bool, session_id: str
	) -> None:
		calls.append(("result", name, output, is_error, session_id))

	out = await run_final_only(
		pool,  # type: ignore[arg-type]
		session_id="ilink:default",
		text="截图",
		cfg=_CFG,
		on_tool_call=on_tool_call,
		on_tool_result=on_tool_result,
	)
	assert out == "好了"
	assert calls[0][:2] == ("call", "Screenshot")
	assert calls[1][:3] == ("result", "Screenshot", "saved")


@pytest.mark.asyncio
async def test_run_final_only_prefers_result_over_final():
	events = [
		FinalEvent(text="from_final"),
		ResultEvent(subtype="success", result="from_result"),
	]
	pool = _FakePool(events)
	out = await run_final_only(pool, session_id="s", text="x", cfg=_CFG)  # type: ignore[arg-type]
	assert out == "from_result"


@pytest.mark.asyncio
async def test_run_final_only_mirrors_permission_and_task_state():
	events = [
		TaskStateEvent(session_id="ilink:p", turn_id="t1", task_status="waiting_permission"),
		PermissionPendingEvent(
			request_id="r1",
			tool_name="Write",
			tool_input={"path": ".git/x"},
			reason="needs_confirmation",
			prompt="Write to .git/x?",
		),
		PermissionResolvedEvent(
			request_id="r1", approved=True, actor="user", reason="user_decided"
		),
		TaskStateEvent(session_id="ilink:p", turn_id="t1", task_status="running"),
		FinalEvent(text="done"),
		ResultEvent(subtype="success", result="done"),
	]
	pool = _FakePool(events)
	perms: list[dict[str, object]] = []
	tasks: list[str] = []

	def on_permission(payload: dict, session_id: str) -> None:
		perms.append(payload)

	def on_task_state(status: str, session_id: str) -> None:
		tasks.append(status)

	out = await run_final_only(
		pool,
		session_id="ilink:p",
		text="x",
		cfg=_CFG,
		on_permission=on_permission,
		on_task_state=on_task_state,
	)
	assert out == "done"
	assert perms[0]["kind"] == "permission_pending"
	assert perms[0]["request_id"] == "r1"
	assert perms[1]["kind"] == "permission_resolved"
	assert tasks == ["waiting_permission", "running"]


@pytest.mark.asyncio
async def test_run_final_only_stopped():
	events = [StoppedEvent(reason="aborted")]
	pool = _FakePool(events)
	out = await run_final_only(pool, session_id="s", text="x", cfg=_CFG)  # type: ignore[arg-type]
	assert out == "[stopped: aborted]"


def test_job_store_lifecycle():
	store = JobStore()
	rec = store.create(session_id="remote:default", text="hello")
	assert rec.status == "queued"
	got = store.get(rec.job_id)
	assert got is not None
	assert got.text == "hello"
	store.mark_running(rec.job_id)
	assert store.get(rec.job_id).status == "running"  # type: ignore[union-attr]
	store.mark_done(rec.job_id, "answer")
	pub = store.get(rec.job_id).to_public()  # type: ignore[union-attr]
	assert pub["status"] == "done"
	assert pub["final_text"] == "answer"
	assert "error" not in pub

	err = store.create(session_id="s", text="boom")
	store.mark_error(err.job_id, "fail")
	pub2 = store.get(err.job_id).to_public()  # type: ignore[union-attr]
	assert pub2["status"] == "error"
	assert pub2["error"] == "fail"
	assert "final_text" not in pub2


def test_job_store_waiting_permission_and_stopping():
	store = JobStore()
	rec = store.create(session_id="remote:w", text="x")
	store.mark_waiting_permission(rec.job_id)
	assert store.get(rec.job_id).status == "waiting_permission"  # type: ignore[union-attr]
	assert store.get(rec.job_id).to_public()["status"] == "waiting_permission"  # type: ignore[union-attr]
	store.mark_stopping(rec.job_id)
	assert store.get(rec.job_id).status == "stopping"  # type: ignore[union-attr]


def test_verify_remote_token(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.delenv("XEYO_REMOTE_TOKEN", raising=False)
	assert remote_enabled() is False
	with pytest.raises(ValueError, match="disabled"):
		verify_remote_token(None, None)

	monkeypatch.setenv("XEYO_REMOTE_TOKEN", "secret-token")
	assert remote_enabled() is True
	with pytest.raises(ValueError, match="missing"):
		verify_remote_token(None, None)
	with pytest.raises(ValueError, match="invalid"):
		verify_remote_token("Bearer wrong", None)
	verify_remote_token("Bearer secret-token", None)
	verify_remote_token(None, "secret-token")
	verify_remote_token("Bearer wrong", "secret-token")


@pytest.mark.asyncio
async def test_final_only_runner_serial_queue(monkeypatch: pytest.MonkeyPatch):
	"""同一 session 上的两个 job 依次运行。"""
	order: list[str] = []
	# γ4 起远程入站文本带 untrusted 围栏进引擎；假引擎原样回显，
	# 因此排序标记与断言都用围栏后的字符串。
	from prompt.fence import fence_remote_user_text

	fa = fence_remote_user_text("a", source="wechat")
	fb = fence_remote_user_text("b", source="wechat")

	class Engine:
		async def submit(self, text: str) -> AsyncIterator[Any]:
			order.append(f"start:{text}")
			await asyncio.sleep(0.08)
			order.append(f"end:{text}")
			yield FinalEvent(text=f"ok:{text}")

		def interrupt(self) -> None:
			pass

	class Pool:
		def __init__(self) -> None:
			self._busy: set[str] = set()
			self._lease = 0

		def try_begin(self, session_id: str) -> int | None:
			if session_id in self._busy:
				return None
			self._busy.add(session_id)
			self._lease += 1
			return self._lease

		def end(self, session_id: str, lease_id: int | None = None) -> None:
			self._busy.discard(session_id)

		def take_pending_interrupt(self, _session_id: str) -> bool:
			return False

		def get_or_create(self, *_a: Any, **_k: Any) -> Engine:
			return Engine()

	import channels.runner as runner_mod

	monkeypatch.setattr(runner_mod, "resolve_remote_model_config", lambda: _CFG)

	store = JobStore()
	runner = FinalOnlyRunner(Pool(), store)  # type: ignore[arg-type]
	j1 = runner.enqueue(session_id="remote:default", text="a")
	j2 = runner.enqueue(session_id="remote:default", text="b")
	for _ in range(100):
		r1 = store.get(j1)
		r2 = store.get(j2)
		assert r1 and r2
		if r1.status in ("done", "error") and r2.status in ("done", "error"):
			break
		await asyncio.sleep(0.02)

	assert store.get(j1).status == "done"  # type: ignore[union-attr]
	assert store.get(j2).status == "done"  # type: ignore[union-attr]
	assert store.get(j1).final_text == f"ok:{fa}"  # type: ignore[union-attr]
	assert store.get(j2).final_text == f"ok:{fb}"  # type: ignore[union-attr]
	assert order.index(f"end:{fa}") < order.index(f"start:{fb}")


@pytest.mark.asyncio
async def test_remote_job_status_waiting_permission(monkeypatch: pytest.MonkeyPatch):
	"""远程任务命中权限时，JobStore 显示 waiting_permission，批准后回 running 并 done。"""

	class Engine:
		async def submit(self, text: str) -> AsyncIterator[Any]:
			yield PermissionPendingEvent(
				request_id="r1",
				tool_name="Write",
				tool_input={"path": "x"},
				reason="needs_confirmation",
				prompt="ok?",
			)
			await asyncio.sleep(0.05)
			yield PermissionResolvedEvent(
				request_id="r1", approved=True, actor="user", reason="user_decided"
			)
			await asyncio.sleep(0.02)
			yield FinalEvent(text="ok")
			yield ResultEvent(subtype="success", result="ok")

		def interrupt(self) -> None:
			pass

	class Pool:
		def __init__(self) -> None:
			self._busy: set[str] = set()
			self._lease = 0

		def try_begin(self, session_id: str) -> int | None:
			if session_id in self._busy:
				return None
			self._busy.add(session_id)
			self._lease += 1
			return self._lease

		def end(self, session_id: str, lease_id: int | None = None) -> None:
			self._busy.discard(session_id)

		def take_pending_interrupt(self, _session_id: str) -> bool:
			return False

		def get_or_create(self, *_a: Any, **_k: Any) -> Engine:
			return Engine()

	import channels.runner as runner_mod

	monkeypatch.setattr(runner_mod, "resolve_remote_model_config", lambda: _CFG)

	store = JobStore()
	runner = FinalOnlyRunner(Pool(), store)  # type: ignore[arg-type]
	jid = runner.enqueue(session_id="remote:w", text="x")
	observed: set[str] = set()
	for _ in range(200):
		rec = store.get(jid)
		if rec is not None:
			observed.add(rec.status)
			if rec.status in ("done", "error"):
				break
		await asyncio.sleep(0.01)

	assert store.get(jid).status == "done"  # type: ignore[union-attr]
	assert "waiting_permission" in observed


def test_job_not_found_public():
	assert JobStore().get("missing") is None
