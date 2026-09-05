"""File Helper channel：final-only 回调、去重、截图指令不进模型。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from channels.base import InboundMessage
from channels.filehelper import SESSION_ID
from channels.filehelper.bridge import FileHelperBridge
from channels.filehelper.channel import FileHelperChannel
from channels.filehelper.commands import (
	is_screenshot_command,
	looks_like_screenshot_request,
	parse_command,
	with_screenshot_nudge,
)
from channels.filehelper.page import chunk_text
from channels.filehelper.prefix import xeyo_reply
from channels.filehelper.seen import SeenIndex, added_messages
from channels.jobs import JobRecord, JobStore
from channels.runner import FinalOnlyRunner, run_final_only
from msgtypes.events import (
	AssistantDelta,
	FinalEvent,
	PermissionPendingEvent,
	ResultEvent,
	TaskStateEvent,
	ToolCallEvent,
	ToolResultEvent,
)
from server.session_pool import ModelConfig

_CFG = ModelConfig(
	provider="deepseek",
	api_key="k",
	base_url="https://example.com/v1",
	model="m",
)


class _FakeEngine:
	def __init__(self, events: list[Any]) -> None:
		self._events = events

	async def submit(self, _text: str) -> AsyncIterator[Any]:
		for ev in self._events:
			yield ev

	def interrupt(self) -> None:
		pass


class _FakePool:
	def __init__(self, events: list[Any]) -> None:
		self._events = events
		self._busy = False
		self.lease_id = 1

	def try_begin(self, _session_id: str) -> int | None:
		if self._busy:
			return None
		self._busy = True
		return self.lease_id

	def end(self, _session_id: str, lease_id: int | None = None) -> None:
		self._busy = False

	def get_or_create(self, *_a: Any, **_k: Any) -> _FakeEngine:
		return _FakeEngine(self._events)

	def take_pending_interrupt(self, _session_id: str) -> bool:
		return False


class _RecordingBridge:
	def __init__(self) -> None:
		self.texts: list[str] = []
		self.files: list[Path] = []

	async def send_text(self, text: str) -> None:
		self.texts.append(text)

	async def send_file(self, path: Path) -> None:
		self.files.append(path)


def test_screenshot_is_not_a_bypass_command():
	assert is_screenshot_command("截图") is False
	assert parse_command("截图") is None
	assert parse_command("/screenshot") is None
	assert parse_command("/help") is not None and parse_command("/help").name == "help"
	assert parse_command("状态") is not None and parse_command("状态").name == "status"
	assert parse_command("/stop") is not None and parse_command("/stop").name == "stop"
	assert parse_command("目录") is not None and parse_command("目录").name == "cwd"
	assert parse_command("随便问问") is None


def test_screenshot_nudge_forces_tool_on_ilink_wording():
	n = with_screenshot_nudge("截图")
	assert "Screenshot" in n
	assert "不要让用户切换通道" in n
	assert looks_like_screenshot_request("/screenshot")
	assert looks_like_screenshot_request("看一下屏幕")
	assert with_screenshot_nudge("/help") == "/help"
	assert with_screenshot_nudge("写个函数") == "写个函数"


def test_xeyo_reply_prefix():
	assert xeyo_reply("ok") == "[XEYO]\nok"
	assert xeyo_reply("[XEYO]\nok") == "[XEYO]\nok"


def test_seen_skips_outbound_and_history():
	idx = SeenIndex()
	idx.seed(["old"])
	idx.remember_outbound("THE_FINAL")
	assert idx.take_inbound(["old", "THE_FINAL", "hi"]) == ["hi"]
	assert idx.take_inbound(["hi"]) == []


def test_remember_outbound_covers_prefixed_lines():
	idx = SeenIndex()
	idx.remember_outbound("[XEYO]\nTHE_FINAL")
	assert idx.take_inbound(["[XEYO]", "THE_FINAL"]) == []


def test_echo_blob_with_wechat_chrome_is_dropped():
	idx = SeenIndex()
	idx.remember_outbound("[XEYO]\n我是 XEYO，一个编码助手")
	assert idx.take_inbound(["下午 7:32\n[XEYO]\n我是 XEYO，一个编码助手"]) == []
	assert idx.take_inbound(["[XEYO] 我是 XEYO，一个编码助手"]) == []
	assert (
		idx.take_inbound(
			["[XEYO]\n我注意到我们似乎在互相重复对方的话。我在等待你的具体任务需求。"]
		)
		== []
	)


def test_echo_does_not_drop_real_user_before_reply():
	idx = SeenIndex()
	idx.remember_outbound("[XEYO]\n我是助手")
	assert idx.take_inbound(["你是谁\n下午 7:33\n[XEYO]\n我是助手"]) == ["你是谁"]
	assert idx.take_inbound(["写个函数"]) == ["写个函数"]


def test_filehelper_slogan_is_not_inbound():
	idx = SeenIndex()
	idx.seed(["seed"])
	assert idx.take_inbound(["使用文件传输助手，手机电脑轻松互传文件。"]) == []
	assert idx.take_inbound(["帮我把 report.pdf 发到微信"]) == ["帮我把 report.pdf 发到微信"]


def test_is_own_reply_prefix():
	from channels.filehelper.prefix import is_own_reply

	assert is_own_reply("[XEYO]\nhello")
	assert is_own_reply("[XEYO] hello")
	assert is_own_reply("下午 7:32\n[XEYO]\nhello")
	assert not is_own_reply("你是谁")
	assert not is_own_reply("[远程]\n你是谁")


def test_added_messages_first_snapshot_empty():
	assert added_messages("", "hello\nworld") == []
	assert added_messages("hello", "hello\nworld") == ["world"]
	assert added_messages("a\nb", "a\nb\nc") == ["c"]


def test_chunk_text():
	assert chunk_text("ab", 1500) == ["ab"]
	assert chunk_text("abcdef", 2) == ["ab", "cd", "ef"]
	assert chunk_text("") == []


def test_send_marker_uses_tail():
	from channels.filehelper.page import _send_marker

	assert _send_marker("short") == "short"
	long = "x" * 80
	assert _send_marker(long) == long[-48:]


@pytest.mark.asyncio
async def test_channel_inbound_enqueues():
	store = JobStore()
	enqueued: list[str] = []

	class _Runner:
		def enqueue(self, *, session_id: str, text: str, images=None) -> str:
			enqueued.append(f"{session_id}:{text}")
			return store.create(session_id=session_id, text=text).job_id

	ch = FileHelperChannel(_Runner(), _RecordingBridge())  # type: ignore[arg-type]
	job_id = await ch.handle_inbound(
		InboundMessage(text="do work", session_id=SESSION_ID, sender_id="phone")
	)
	assert enqueued == [f"{SESSION_ID}:do work"]
	assert job_id.startswith("job-")


@pytest.mark.asyncio
async def test_send_job_result_only_filehelper_and_final_text():
	bridge = _RecordingBridge()
	ch = FileHelperChannel(FinalOnlyRunner(_FakePool([]), JobStore()), bridge)  # type: ignore[arg-type]
	await ch.send_job_result(
		JobRecord(
			job_id="j1",
			session_id="remote:default",
			text="x",
			status="done",
			final_text="SHOULD_NOT_SEND",
		)
	)
	assert bridge.texts == []
	await ch.send_job_result(
		JobRecord(
			job_id="j2",
			session_id=SESSION_ID,
			text="x",
			status="done",
			final_text="THE_FINAL",
		)
	)
	assert bridge.texts == ["[XEYO]\nTHE_FINAL"]
	await ch.send_job_result(
		JobRecord(
			job_id="j3",
			session_id=SESSION_ID,
			text="x",
			status="error",
			error="boom",
		)
	)
	assert bridge.texts[-1] == "[XEYO]\nboom"


@pytest.mark.asyncio
async def test_run_final_only_ignores_tools():
	events = [
		AssistantDelta(text="mid"),
		ToolCallEvent(name="Bash", input={}),
		ToolResultEvent(name="Bash", output="ok"),
		FinalEvent(text="THE_FINAL"),
		ResultEvent(subtype="success", result="THE_FINAL"),
	]
	out = await run_final_only(
		_FakePool(events),  # type: ignore[arg-type]
		session_id=SESSION_ID,
		text="hi",
		cfg=_CFG,
	)
	assert out == "THE_FINAL"


@pytest.mark.asyncio
async def test_run_final_only_still_returns_final_with_permission_events():
	"""run_final_only 本身只收终稿；权限推送由 FinalOnlyRunner.on_permission 负责。"""
	events = [
		PermissionPendingEvent(
			request_id="r1",
			tool_name="Write",
			tool_input={"path": "x"},
			reason="needs_confirmation",
			prompt="ok?",
		),
		TaskStateEvent(
			session_id=SESSION_ID, turn_id="t1", task_status="waiting_permission"
		),
		FinalEvent(text="THE_FINAL"),
		ResultEvent(subtype="success", result="THE_FINAL"),
	]
	out = await run_final_only(
		_FakePool(events),  # type: ignore[arg-type]
		session_id=SESSION_ID,
		text="hi",
		cfg=_CFG,
	)
	assert out == "THE_FINAL"


@pytest.mark.asyncio
async def test_runner_on_complete_sends_final(monkeypatch: pytest.MonkeyPatch):
	import channels.runner as runner_mod

	monkeypatch.setattr(runner_mod, "resolve_remote_model_config", lambda: _CFG)

	class Engine:
		async def submit(self, text: str) -> AsyncIterator[Any]:
			assert '<user_message untrusted="true"' in text
			assert "task" in text
			yield AssistantDelta(text="noise")
			yield ToolCallEvent(name="Read", input={})
			yield FinalEvent(text="ok:task")

		def interrupt(self) -> None:
			pass

	class Pool:
		def try_begin(self, _s: str) -> int | None:
			return 1

		def end(self, _s: str, lease_id: int | None = None) -> None:
			return None

		def take_pending_interrupt(self, _s: str) -> bool:
			return False

		def get_or_create(self, *_a: Any, **_k: Any) -> Engine:
			return Engine()

	completed: list[str] = []

	async def on_complete(rec: JobRecord) -> None:
		completed.append(rec.final_text or "")

	store = JobStore()
	runner = FinalOnlyRunner(Pool(), store, on_complete=on_complete)  # type: ignore[arg-type]
	jid = runner.enqueue(session_id=SESSION_ID, text="task")
	for _ in range(80):
		rec = store.get(jid)
		if rec and rec.status in ("done", "error"):
			break
		await asyncio.sleep(0.02)
	assert store.get(jid).status == "done"  # type: ignore[union-attr]
	assert completed == ["ok:task"]


@pytest.mark.asyncio
async def test_dispatch_screenshot_goes_to_model():
	bridge = FileHelperBridge()
	inbound: list[str] = []
	sent: list[str] = []

	async def handler(text: str) -> None:
		inbound.append(text)

	async def send_text(text: str) -> None:
		sent.append(text)

	bridge.set_inbound_handler(handler)
	bridge.send_text = send_text  # type: ignore[method-assign]
	await bridge.dispatch_inbound("截图")
	await bridge.dispatch_inbound("  /screenshot ")
	await bridge.dispatch_inbound("写个函数")
	await bridge.dispatch_inbound("/help")
	assert inbound == ["截图", "  /screenshot ", "写个函数"]
	assert any("可用指令" in s for s in sent)


def test_is_icon_png_filters_avatar():
	from channels.filehelper.page import _is_icon_png

	assert not _is_icon_png(b"x" * 900, area=140 * 140)
	assert _is_icon_png(b"x" * 400, area=80 * 80)
	assert _is_icon_png(b"x" * 800, side=110)


def test_qr_rev_bumps_only_when_png_changes():
	b = FileHelperBridge()
	assert b.qr_rev == 0
	b._set_qr(b"png-a")
	assert b.qr_rev == 1
	b._set_qr(b"png-a")
	assert b.qr_rev == 1
	b._set_qr(b"png-b")
	assert b.qr_rev == 2
	b._set_qr(None)
	assert b.qr_rev == 2
	assert b.qr_png() is None


def test_filehelper_http_status_and_page():
	from fastapi.testclient import TestClient

	from server.app import app

	c = TestClient(app)
	r = c.get("/v1/filehelper/status")
	assert r.status_code == 200
	body = r.json()
	assert body["session_id"] == SESSION_ID
	assert body["state"] == "stopped"
	assert body["logged_in"] is False
	assert "events" in body
	assert "hint" in body
	assert "qr_rev" in body
	assert body["qr_rev"] == 0
	assert body["streaming"] is False
	assert "stream_text" not in body
	assert "stream_status" not in body
	qr = c.get("/v1/filehelper/qr.png")
	assert qr.status_code == 404
	page = c.get("/filehelper/")
	assert page.status_code == 200
	assert "text/html" in page.headers.get("content-type", "")


def test_status_stream_from_and_omit_jobs():
	import channels.filehelper.service as svc

	m = svc._mirror
	prev = (m._stream_active, m._stream_text, m._stream_status)
	try:
		m._stream_active = True
		m._stream_text = "hello world"
		m._stream_status = "thinking…"
		full = svc.status_payload()
		assert full["stream_text"] == "hello world"
		assert full["stream_len"] == 11
		assert "recent_jobs" in full
		delta = svc.status_payload(omit_jobs=True, stream_from=5)
		assert "recent_jobs" not in delta
		assert delta["stream_text"] == " world"
		assert delta["stream_len"] == 11
		reset = svc.status_payload(omit_jobs=True, stream_from=99)
		assert reset["stream_reset"] is True
		assert reset["stream_text"] == "hello world"
		m._stream_active = False
		idle = svc.status_payload(omit_jobs=True)
		assert idle["streaming"] is False
		assert "stream_text" not in idle
		assert "stream_status" not in idle
	finally:
		m._stream_active, m._stream_text, m._stream_status = prev


def test_seen_persist_roundtrip(tmp_path: Path):
	from channels.filehelper.seen import SeenIndex, seen_store_path

	path = seen_store_path(tmp_path)
	idx = SeenIndex()
	idx.remember_outbound("[XEYO]\nhello")
	idx.seed(["old-msg"])
	idx.save(path)
	loaded = SeenIndex()
	loaded.load(path)
	assert loaded.take_inbound(["old-msg", "hello"]) == []
	assert loaded.take_inbound(["new"]) == ["new"]


@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_filehelper_sse_events_route():
	"""SSE 路由首帧为 state。

	不用 TestClient.c.stream：该实现在 Windows 上对无限 StreamingResponse
	会永久阻塞（portal.call 等 app 完成才返回），直接驱动 ASGI 响应对象。
	"""
	from channels.filehelper.api import filehelper_events

	resp = await filehelper_events()
	it = resp.body_iterator
	try:
		first = await anext(it)
		assert first.startswith("event: state")
	finally:
		try:
			await it.aclose()
		except Exception:
			pass


def test_inbound_queue():
	from channels.filehelper.inbound_queue import InboundQueue

	q = InboundQueue()
	assert q.push("a") == 1
	assert q.push("b") == 2
	assert q.pop() == "a"
	assert q.pop() == "b"
	assert q.pop() is None


def test_status_omit_jobs_query():
	from fastapi.testclient import TestClient

	from server.app import app

	c = TestClient(app)
	body = c.get("/v1/filehelper/status?omit_jobs=1").json()
	assert "recent_jobs" not in body
	assert body["streaming"] is False
	assert "stream_text" not in body
