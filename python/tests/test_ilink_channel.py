"""iLink / ClawBot 通道：HTTP 客户端、登录状态机、互斥启停。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from channels.base import InboundMessage
from channels.ilink import SESSION_ID
from channels.ilink.channel import ILinkChannel
from channels.ilink.client import ILinkClient, collect_update_msgs, decode_qr_payload, extract_text, make_headers
from channels.jobs import JobRecord, JobStore
from channels.runner import FinalOnlyRunner

# 1×1 像素 PNG
_PNG_B64 = (
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _EnqueueRunner:
	def __init__(self) -> None:
		self.texts: list[tuple[str, str]] = []
		self.jobs: list[dict[str, Any]] = []

	def enqueue(self, *, session_id: str, text: str, images=None, **k: Any) -> str:
		self.texts.append((session_id, text))
		self.jobs.append(
			{
				"session_id": session_id,
				"text": text,
				"reply_peer": k.get("reply_peer"),
				"reply_ctx": k.get("reply_ctx"),
			}
		)
		return "job-ilink"


class _RecordingBridge:
	def __init__(self) -> None:
		self.texts: list[str] = []

	async def send_text(self, text: str, **_k: Any) -> None:
		self.texts.append(text)


def test_headers_and_extract_text():
	h = make_headers("tok-1")
	assert h["Authorization"] == "Bearer tok-1"
	assert h["AuthorizationType"] == "ilink_bot_token"
	assert h["SKRouteTag"] == "1001"
	assert h["iLink-App-Id"] == "bot"
	assert "X-WECHAT-UIN" in h
	assert extract_text({"item_list": [{"type": 1, "text_item": {"text": "你好"}}]}) == "你好"
	assert extract_text({"item_list": [{"type": 2, "text_item": {"text": "x"}}]}) == "x"
	assert extract_text({"itemList": [{"textItem": {"text": "驼峰"}}]}) == "驼峰"
	assert extract_text({"item_list": [{"type": 5, "voice_item": {"text": "语音转写"}}]}) == "语音转写"
	assert extract_text({"itemList": [{"textItem": "纯字符串"}]}) == "纯字符串"
	assert extract_text({"text": "顶层"}) == "顶层"


def test_collect_update_msgs_shapes():
	assert collect_update_msgs({"msgs": [{"a": 1}]}) == [{"a": 1}]
	assert collect_update_msgs({"data": {"msgs": [{"a": 2}]}}) == [{"a": 2}]
	assert collect_update_msgs({"msg_list": [{"a": 3}]}) == [{"a": 3}]
	assert collect_update_msgs({"msg": {"a": 4}}) == [{"a": 4}]
	assert collect_update_msgs({"ret": 0}) == []


def test_decode_qr_payload():
	blob, url = decode_qr_payload("https://ilinkai.weixin.qq.com/qr.png")
	assert blob is None and url and url.startswith("https://")
	blob, url = decode_qr_payload(f"data:image/png;base64,{_PNG_B64}")
	assert blob and url is None and blob[:8] == b"\x89PNG\r\n\x1a\n"
	blob, url = decode_qr_payload("<svg xmlns='x'></svg>")
	assert blob and blob.startswith(b"<svg") and url is None


def test_qr_png_from_weixin_url():
	from channels.ilink.qr_png import qr_matrix, render_qr_png

	url = "https://weixin.qq.com/x/cAbCdEfGhIj"
	blob = render_qr_png(url)
	assert blob.startswith(b"\x89PNG\r\n\x1a\n")
	assert len(blob) > 200
	m = qr_matrix(url)
	for i in range(7):
		assert m[0][i] == 1 and m[6][i] == 1
		assert m[i][0] == 1 and m[i][6] == 1
	assert m[3][3] == 1
	assert m[1][1] == 0
	n = len(m)
	assert m[0][n - 1] == 1 and m[n - 1][0] == 1


@pytest.mark.asyncio
async def test_materialize_weixin_url_does_not_download(reset_ilink):
	import channels.ilink.service as svc

	class FakeClient:
		async def fetch_bytes(self, _url: str) -> tuple[bytes, str]:
			raise AssertionError("weixin login URL is not an image")

	await svc._materialize_qr(
		FakeClient(),  # type: ignore[arg-type]
		{"qrcode_img_content": "https://weixin.qq.com/x/cAbCdEfGhIj"},
	)
	blob = svc._bridge.qr_png()
	assert blob is not None and blob.startswith(b"\x89PNG\r\n\x1a\n")
	assert svc._bridge.qr_mime() == "image/png"



@pytest.mark.asyncio
async def test_sendmessage_includes_context_token():
	captured: list[dict[str, Any]] = []

	def handler(request: httpx.Request) -> httpx.Response:
		if "sendmessage" in str(request.url):
			captured.append(json.loads(request.content.decode("utf-8")))
			return httpx.Response(200, json={"ret": 0})
		return httpx.Response(404, json={"ret": -1, "errmsg": str(request.url)})

	client = ILinkClient(transport=httpx.MockTransport(handler))
	await client.sendmessage(
		"bot-tok",
		to_user_id="user-1",
		context_token="ctx-abc",
		text="hello",
	)
	assert len(captured) == 1
	msg = captured[0]["msg"]
	assert msg["context_token"] == "ctx-abc"
	assert msg["from_user_id"] == ""
	assert msg["to_user_id"] == "user-1"
	assert msg["message_type"] == 2
	assert msg["message_state"] == 2
	assert msg["client_id"].startswith("xeyo-")
	assert captured[0]["base_info"]["bot_agent"] == "XEYO/0.1"
	await client.aclose()


@pytest.mark.asyncio
async def test_notifystart_and_stop_paths():
	paths: list[str] = []

	def handler(request: httpx.Request) -> httpx.Response:
		paths.append(str(request.url))
		return httpx.Response(200, json={"ret": 0})

	client = ILinkClient(transport=httpx.MockTransport(handler))
	assert (await client.notifystart("tok"))["ret"] == 0
	assert (await client.notifystop("tok"))["ret"] == 0
	assert any("notifystart" in p for p in paths)
	assert any("notifystop" in p for p in paths)
	await client.aclose()


@pytest.mark.asyncio
async def test_getupdates_uses_dedicated_poll_client():
	seen: list[str] = []

	def handler(request: httpx.Request) -> httpx.Response:
		seen.append(str(request.url))
		return httpx.Response(200, json={"ret": 0, "msgs": [], "get_updates_buf": "B"})

	client = ILinkClient(transport=httpx.MockTransport(handler))
	data = await client.getupdates("tok", "")
	assert data["ret"] == 0
	assert data["get_updates_buf"] == "B"
	assert any("getupdates" in u for u in seen)
	await client.reset_poll_http()
	assert client._poll_http is None
	await client.aclose()


@pytest.mark.asyncio
async def test_get_bot_qrcode_falls_back_to_get():
	methods: list[str] = []

	def handler(request: httpx.Request) -> httpx.Response:
		methods.append(request.method)
		if request.method == "POST":
			return httpx.Response(200, json={"ret": 0})
		return httpx.Response(
			200,
			json={"ret": 0, "qrcode": "QR-1", "qrcode_img_content": _PNG_B64},
		)

	client = ILinkClient(transport=httpx.MockTransport(handler))
	data = await client.get_bot_qrcode()
	assert data["qrcode"] == "QR-1"
	assert methods == ["POST", "GET"]
	await client.aclose()


@pytest.mark.asyncio
async def test_channel_inbound_skips_own_reply():
	runner = _EnqueueRunner()
	ch = ILinkChannel(runner, _RecordingBridge())  # type: ignore[arg-type]
	await ch.handle_inbound(
		InboundMessage(text="[XEYO]\nok", session_id=SESSION_ID, sender_id="ilink")
	)
	assert runner.texts == []
	await ch.handle_inbound(
		InboundMessage(text="你好", session_id=SESSION_ID, sender_id="ilink")
	)
	assert runner.texts == [(SESSION_ID, "你好")]


@pytest.mark.asyncio
async def test_send_job_result_prefixes():
	bridge = _RecordingBridge()
	ch = ILinkChannel(FinalOnlyRunner(None, JobStore()), bridge)  # type: ignore[arg-type]
	await ch.send_job_result(
		JobRecord(
			job_id="j1",
			session_id=SESSION_ID,
			text="q",
			status="done",
			final_text="答案",
		)
	)
	assert bridge.texts == ["[XEYO]\n答案"]
	await ch.send_job_result(
		JobRecord(
			job_id="j1b",
			session_id=SESSION_ID,
			text="q",
			status="done",
			final_text="带上下文",
			reply_peer="u@im.wechat",
			reply_ctx="ctx-keep",
		)
	)
	assert bridge.texts[-1] == "[XEYO]\n带上下文"
	await ch.send_job_result(
		JobRecord(
			job_id="j2",
			session_id="filehelper:default",
			text="q",
			status="done",
			final_text="nope",
		)
	)
	assert bridge.texts == ["[XEYO]\n答案", "[XEYO]\n带上下文"]


def test_credentials_roundtrip(tmp_path, monkeypatch):
	from channels.ilink import store

	monkeypatch.setattr(store, "credentials_dir", lambda: tmp_path)
	store.save_credentials({"bot_token": "abc"})
	assert (tmp_path / "credentials.json").is_file()
	assert store.load_credentials()["bot_token"] == "abc"
	store.clear_credentials()
	assert store.load_credentials() == {}


class _DummyRunner:
	_on_complete = None

	def set_on_complete(self, fn) -> None:  # noqa: ANN001
		self._on_complete = fn

	def add_on_complete(self, fn) -> None:  # noqa: ANN001
		self._on_complete = fn

	def remove_on_complete(self, fn) -> None:  # noqa: ANN001
		if self._on_complete is fn:
			self._on_complete = None

	def set_on_delta(self, fn) -> None:  # noqa: ANN001
		pass

	def set_on_status(self, fn) -> None:  # noqa: ANN001
		pass

	def set_on_tool_call(self, fn) -> None:  # noqa: ANN001
		pass

	def set_on_tool_result(self, fn) -> None:  # noqa: ANN001
		pass

	def set_on_permission(self, fn) -> None:  # noqa: ANN001
		pass

	def set_on_task_state(self, fn) -> None:  # noqa: ANN001
		pass

	def session_busy(self, _sid: str) -> bool:
		return False

	def interrupt_session(self, _sid: str) -> bool:
		return False

	def enqueue(self, **_k: Any) -> str:
		return "job"


@pytest.fixture
async def reset_ilink(tmp_path, monkeypatch):
	from channels.ilink import store
	import channels.ilink.service as svc

	monkeypatch.setattr(store, "credentials_dir", lambda: tmp_path)
	await svc.stop(None)
	yield
	await svc.stop(None)


@pytest.mark.asyncio
async def test_login_qr_state_machine(reset_ilink, monkeypatch):
	import channels.ilink.service as svc

	async def _no_sleep(_t: float = 0) -> None:
		return

	monkeypatch.setattr(svc.asyncio, "sleep", _no_sleep)
	seq = {"n": 0}

	class FakeClient:
		async def get_bot_qrcode(self, _tokens):  # noqa: ANN001
			return {"qrcode": "ABC", "qrcode_img_content": _PNG_B64}

		async def get_qrcode_status(self, qrcode, base_url=None):  # noqa: ANN001
			assert qrcode == "ABC"
			seq["n"] += 1
			if seq["n"] == 1:
				return {"status": "wait"}
			if seq["n"] == 2:
				return {"status": "scaned"}
			return {"status": "confirmed", "bot_token": "T1"}

	svc._bridge._stop = asyncio.Event()
	token = await svc._login_with_qr(FakeClient(), "")  # type: ignore[arg-type]
	assert token == "T1"
	assert seq["n"] == 3
	assert svc._bridge.qr_png()


@pytest.mark.asyncio
async def test_inbound_getupdates_sets_context_token(reset_ilink):
	import channels.ilink.service as svc

	got: list[str] = []

	async def on_in(text: str, images=None) -> None:
		got.append(text)

	svc._bridge.set_inbound_handler(on_in)
	svc._bridge._client = None
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "user-1",
			"context_token": "ctx-abc",
			"item_list": [{"type": 1, "text_item": {"text": "你好"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert svc._bridge.peer_id == "user-1"
	assert svc._bridge.context_token == "ctx-abc"
	assert got == ["你好"]

	await svc._handle_user_msg(
		{
			"message_type": 1,
			"group_id": "g1",
			"from_user_id": "user-2",
			"context_token": "ctx-drop",
			"item_list": [{"type": 1, "text_item": {"text": "群消息"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert got == ["你好"]
	assert svc._bridge.context_token == "ctx-abc"

	await svc._handle_user_msg(
		{
			"message_type": 1,
			"group_id": "u@im.wechat#bot@im.bot",
			"from_user_id": "u@im.wechat",
			"context_token": "ctx-dm",
			"item_list": [{"type": 1, "text_item": {"text": "私聊"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert got == ["你好", "私聊"]
	assert svc._bridge.context_token == "ctx-dm"


@pytest.mark.asyncio
async def test_inbound_image_reaches_handler(reset_ilink, tmp_path, monkeypatch):
	import channels.ilink.service as svc
	from channels.ilink import media as media_mod
	from channels.ilink.crypto import encode_cdn_aes_key, encrypt_aes_ecb

	monkeypatch.setattr(media_mod, "inbound_dir", lambda: tmp_path)
	got: list[tuple[str, list[str] | None]] = []

	async def on_in(text: str, images=None) -> None:
		got.append((text, images))

	key = bytes(range(16))
	png = b"\x89PNG\r\n\x1a\n" + b"hi"
	ct = encrypt_aes_ecb(png, key)

	class FakeClient:
		async def cdn_download(self, **_k):  # noqa: ANN003
			return ct

		async def getconfig(self, *_a, **_k):  # noqa: ANN001
			return {}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge.set_inbound_handler(on_in)
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "user-1",
			"context_token": "ctx-img",
			"item_list": [
				{
					"type": 2,
					"image_item": {
						"aeskey": key.hex(),
						"media": {
							"encrypt_query_param": "dl",
							"aes_key": encode_cdn_aes_key(key),
						},
					},
				}
			],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert got
	assert "已保存" in got[0][0]
	assert got[0][1]
	assert svc._bridge.context_token == "ctx-img"


@pytest.mark.asyncio
async def test_start_stops_filehelper(reset_ilink, monkeypatch):
	import channels.filehelper.service as fh
	import channels.ilink.service as svc

	stopped: list[bool] = []

	class FH:
		state = "logged_in"

	monkeypatch.setattr(fh, "get_bridge", lambda: FH())

	async def fake_fh_stop(runner=None):  # noqa: ANN001
		stopped.append(True)
		FH.state = "stopped"

	monkeypatch.setattr(fh, "stop", fake_fh_stop)

	async def fake_run(*_a, **_k):
		svc._bridge.state = "logged_in"

	monkeypatch.setattr(svc, "_run", fake_run)
	await svc.start(_DummyRunner(), JobStore())  # type: ignore[arg-type]
	assert stopped == [True]
	assert svc.is_running()


def test_ilink_http_status():
	from fastapi.testclient import TestClient

	from channels.ilink import SESSION_ID as ILINK_SID
	from server.app import app

	c = TestClient(app)
	r = c.get("/v1/ilink/status")
	assert r.status_code == 200
	body = r.json()
	assert body["session_id"] == ILINK_SID
	assert body["last_session_id"] == ILINK_SID
	assert body["state"] == "stopped"
	assert body["channel"] == "ilink"
	assert "events" in body
	assert c.get("/v1/ilink/qr.png").status_code == 404


def test_ilink_sse_format():
	from channels.ilink.broadcast import format_sse
	from channels.ilink.service import status_payload

	chunk = format_sse("state", status_payload(omit_jobs=True))
	assert chunk.startswith("event: state")
	assert "data: " in chunk
	assert '"channel": "ilink"' in chunk or '"channel":"ilink"' in chunk


def test_events_since_pruned_cursor_still_returns_new():
	import channels.ilink.service as svc

	m = svc._mirror
	prev = m._events
	m._events = [
		{"id": "ev-41", "kind": "inbound", "text": "a"},
		{"id": "ev-42", "kind": "inbound", "text": "b"},
	]
	try:
		got = svc.events_since("ev-10")
		assert [e["id"] for e in got] == ["ev-41", "ev-42"]
		assert [e["id"] for e in svc.events_since("ev-41")] == ["ev-42"]
		# 重启后序号回绕，旧游标必须整表重放
		assert [e["id"] for e in svc.events_since("ev-99")] == ["ev-41", "ev-42"]
	finally:
		m._events = prev


@pytest.mark.asyncio
async def test_qr_errmsg_surfaces(reset_ilink):
	import channels.ilink.service as svc

	class FakeClient:
		async def get_bot_qrcode(self, _tokens):  # noqa: ANN001
			return {"ret": -1, "errmsg": "risk control"}

	svc._bridge._stop = asyncio.Event()
	with pytest.raises(RuntimeError, match="risk control"):
		await svc._login_with_qr(FakeClient(), "")  # type: ignore[arg-type]


def test_empty_poll_sleep_only_when_fast():
	from channels.ilink.service import empty_poll_sleep_s

	assert empty_poll_sleep_s(0.0, 10.0) == 0.0
	assert empty_poll_sleep_s(1.0, 1.01) == 0.05
	assert empty_poll_sleep_s(1.0, 1.079) == 0.05
	assert empty_poll_sleep_s(1.0, 1.08) == 0.0
	assert empty_poll_sleep_s(1.0, 36.0) == 0.0


def test_session_expired_reads_ret_or_errcode():
	from channels.ilink.service import _session_expired

	assert _session_expired({"ret": -14})
	assert _session_expired({"errcode": 401})
	assert _session_expired({"ret": 0, "errcode": -13})
	assert not _session_expired({"ret": 0, "errcode": 0})
	assert not _session_expired({})


@pytest.mark.asyncio
async def test_inbound_without_message_type(reset_ilink):
	import channels.ilink.service as svc

	got: list[str] = []

	async def on_in(text: str, images=None) -> None:  # noqa: ANN001
		got.append(text)

	svc._bridge.set_inbound_handler(on_in)
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await svc._handle_user_msg(
		{
			"from_user_id": "user-1",
			"context_token": "ctx",
			"item_list": [{"type": 1, "text_item": {"text": "没类型"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert got == ["没类型"]
	await svc._handle_user_msg(
		{
			"message_type": 2,
			"from_user_id": "user-1",
			"context_token": "ctx",
			"item_list": [{"type": 1, "text_item": {"text": "bot echo"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert got == ["没类型"]
	assert svc._bridge.last_inbound is not None
	assert svc._bridge.last_inbound.get("skip") == "bot_echo"
	await svc._handle_user_msg(
		{
			"message_type": 2,
			"from_user_id": "someone@im.wechat",
			"context_token": "ctx",
			"item_list": [{"type": 1, "text_item": {"text": "用户你好"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert got == ["没类型", "用户你好"]
	assert svc._bridge.last_inbound is not None
	assert svc._bridge.last_inbound.get("skip") is None
	assert svc._bridge.last_inbound.get("from") == "wechat"


@pytest.mark.asyncio
async def test_inbound_enqueues_even_if_handler_noop(reset_ilink):
	import channels.ilink.service as svc

	async def noop(_text: str, images=None) -> None:  # noqa: ANN001
		return

	enqueued = _EnqueueRunner()
	svc._bridge.set_inbound_handler(noop)
	ch = ILinkChannel(enqueued, _RecordingBridge())  # type: ignore[arg-type]
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "u@im.wechat",
			"context_token": "ctx",
			"item_list": [{"type": 1, "text_item": {"text": "你好"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert enqueued.texts == [("ilink:u@im.wechat", "你好")]
	assert svc._bridge.last_inbound is not None
	assert svc._bridge.last_inbound.get("handled") is True


@pytest.mark.asyncio
async def test_text_inbound_does_not_touch_media(reset_ilink, monkeypatch):
	import channels.ilink.media as media_mod
	import channels.ilink.service as svc

	async def boom(*_a: object, **_k: object) -> list[object]:
		raise AssertionError("text inbound must not collect media")

	monkeypatch.setattr(media_mod, "collect_inbound_media", boom)
	enqueued = _EnqueueRunner()
	svc._bridge.set_inbound_handler(None)
	ch = ILinkChannel(enqueued, _RecordingBridge())  # type: ignore[arg-type]
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "u@im.wechat",
			"context_token": "ctx",
			"item_list": [{"type": 1, "text_item": {"text": "在吗"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert enqueued.texts == [("ilink:u@im.wechat", "在吗")]
	assert svc._bridge.last_inbound.get("skip") is None


@pytest.mark.asyncio
async def test_notify_online_expired_is_false(reset_ilink):
	import channels.ilink.service as svc

	class Fake:
		async def notifystart(self, token: str) -> dict:  # noqa: ANN001
			assert token == "tok"
			return {"ret": -14, "errmsg": "session timeout"}

	assert await svc._notify_online(Fake(), "tok") is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_notify_online_network_error_is_nonfatal(reset_ilink):
	import channels.ilink.service as svc

	class Fake:
		async def notifystart(self, _token: str) -> dict:  # noqa: ANN001
			raise httpx.ConnectError("boom")

	assert await svc._notify_online(Fake(), "tok") is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_poll_ret_minus_14_stops(reset_ilink):
	import channels.ilink.service as svc

	class FakeClient:
		base_url = ""

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			return {"ret": -14, "errmsg": "session timeout"}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "BUF"
	svc._bridge._stop = asyncio.Event()
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await svc._poll_loop(ch, _DummyRunner())  # type: ignore[arg-type]
	assert svc._bridge.state == "error"
	assert svc._bridge._buf == ""
	assert svc._bridge._token == ""


def test_poll_read_timeout_matches_long_poll():
	from channels.ilink.service import _POLL_DEADLINE_S, _POLL_READ_S, _POLL_TIMEOUT

	assert _POLL_READ_S >= 35.0
	assert _POLL_TIMEOUT.read == _POLL_READ_S
	assert _POLL_DEADLINE_S > _POLL_READ_S


@pytest.mark.asyncio
async def test_poll_timeout_retries_without_backoff(reset_ilink):
	import time as time_mod

	import channels.ilink.service as svc

	got: list[str] = []
	started = asyncio.Event()

	async def on_in(text: str, images=None) -> None:  # noqa: ANN001
		got.append(text)
		started.set()

	class FakeClient:
		n = 0
		base_url = ""

		async def getupdates(self, _token, buf, timeout=8):  # noqa: ANN001
			self.n += 1
			if self.n == 1:
				raise httpx.TimeoutException("read")
			if self.n == 2:
				return {
					"ret": 0,
					"get_updates_buf": "BUF2",
					"longpolling_timeout_ms": 35000,
					"msgs": [
						{
							"message_type": 1,
							"from_user_id": "user-1",
							"context_token": "ctx-1",
							"item_list": [{"type": 1, "text_item": {"text": "ping"}}],
						}
					],
				}
			svc._bridge._stop.set()
			return {"ret": 0, "get_updates_buf": "BUF2", "msgs": []}

		async def getconfig(self, *_a, **_k):  # noqa: ANN001
			return {}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "BUF1"
	svc._bridge._stop = asyncio.Event()
	svc._bridge.set_inbound_handler(on_in)
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	t0 = time_mod.monotonic()
	task = asyncio.create_task(svc._poll_loop(ch, _DummyRunner()))  # type: ignore[arg-type]
	await asyncio.wait_for(started.wait(), 2)
	assert time_mod.monotonic() - t0 < 0.5
	assert got == ["ping"]
	assert svc._bridge.last_poll_error is None
	await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
async def test_poll_timeout_streak_clears_buf(reset_ilink):
	import channels.ilink.service as svc

	class FakeClient:
		n = 0
		base_url = ""

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			self.n += 1
			if self.n <= 3:
				raise httpx.TimeoutException("read")
			svc._bridge._stop.set()
			return {"ret": 0, "get_updates_buf": buf, "msgs": []}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "STUCK"
	svc._bridge._stop = asyncio.Event()
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await asyncio.wait_for(svc._poll_loop(ch, _DummyRunner()), 3)  # type: ignore[arg-type]
	assert svc._bridge._buf == ""
	assert svc._bridge.last_poll_ret in (0, None, "0")


@pytest.mark.asyncio
async def test_poll_hang_is_cut_by_deadline(reset_ilink, monkeypatch):
	import channels.ilink.service as svc

	monkeypatch.setattr(svc, "_POLL_DEADLINE_S", 0.05)
	got: list[str] = []
	started = asyncio.Event()

	async def on_in(text: str, images=None) -> None:  # noqa: ANN001
		got.append(text)
		started.set()

	class FakeClient:
		n = 0
		base_url = ""

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			self.n += 1
			if self.n <= 2:
				await asyncio.sleep(10)
			svc._bridge._stop.set()
			return {
				"ret": 0,
				"get_updates_buf": "BUF2",
				"msgs": [
					{
						"message_type": 1,
						"from_user_id": "user-1",
						"context_token": "ctx-1",
						"item_list": [{"type": 1, "text_item": {"text": "late"}}],
					}
				],
			}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "BUF1"
	svc._bridge._stop = asyncio.Event()
	svc._bridge.set_inbound_handler(on_in)
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	task = asyncio.create_task(svc._poll_loop(ch, _DummyRunner()))  # type: ignore[arg-type]
	await asyncio.wait_for(started.wait(), 3)
	assert got == ["late"]
	await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
async def test_take_updates_buf_before_handle(reset_ilink):
	import channels.ilink.service as svc

	got: list[str] = []

	async def on_in(text: str, images=None) -> None:  # noqa: ANN001
		got.append(text)
		assert svc._bridge._buf == "BUF2"

	calls: list[str] = []

	class FakeClient:
		n = 0
		base_url = ""

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			calls.append(buf)
			self.n += 1
			if self.n == 1:
				return {
					"ret": 0,
					"get_updates_buf": "BUF2",
					"msgs": [
						{
							"message_type": 1,
							"from_user_id": "user-1",
							"context_token": "ctx-1",
							"item_list": [{"type": 1, "text_item": {"text": "你好"}}],
						}
					],
				}
			svc._bridge._stop.set()
			return {"ret": 0, "get_updates_buf": "BUF2", "msgs": []}

		async def getconfig(self, *_a, **_k):  # noqa: ANN001
			return {}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "BUF1"
	svc._bridge._stop = asyncio.Event()
	svc._bridge.set_inbound_handler(on_in)
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await asyncio.wait_for(svc._poll_loop(ch, _DummyRunner()), 2)  # type: ignore[arg-type]
	assert svc._bridge._buf == "BUF2"
	assert calls[0] == "BUF1"
	assert got == ["你好"]
	assert svc._bridge.last_inbound is not None
	assert svc._bridge.last_inbound.get("delivered") is True


@pytest.mark.asyncio
async def test_stop_flushes_debounced_credentials(reset_ilink, tmp_path, monkeypatch):
	from channels.ilink import store
	import channels.ilink.service as svc

	monkeypatch.setattr(store, "credentials_dir", lambda: tmp_path)
	svc._bridge._token = "tok-flush"
	svc._bridge._buf = "old"
	svc._bridge._client = None
	svc._take_updates_buf({"get_updates_buf": "NEWBUF"})
	assert svc._bridge._buf == "NEWBUF"
	assert not (tmp_path / "credentials.json").is_file()
	await svc.stop(None)
	data = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
	assert data["bot_token"] == "tok-flush"
	assert data["get_updates_buf"] == "NEWBUF"


@pytest.mark.asyncio
async def test_help_command_marks_handled_and_does_not_retry(reset_ilink):
	import channels.ilink.service as svc

	sends: list[str] = []

	class FakeClient:
		n = 0
		base_url = ""
		notifys = 0

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			self.n += 1
			if self.n == 1:
				return {
					"ret": 0,
					"get_updates_buf": "BUF2",
					"msgs": [
						{
							"message_type": 1,
							"from_user_id": "user-1@im.wechat",
							"context_token": "ctx-1",
							"item_list": [{"type": 1, "text_item": {"text": "/help"}}],
						}
					],
				}
			svc._bridge._stop.set()
			return {"ret": 0, "get_updates_buf": "BUF2", "msgs": []}

		async def sendmessage(self, *_a, **_k):  # noqa: ANN001
			sends.append("send")
			return {"ret": 0}

		async def getconfig(self, *_a, **_k):  # noqa: ANN001
			return {}

		async def sendtyping(self, *_a, **_k):  # noqa: ANN001
			return {}

		async def notifystop(self, *_a, **_k):  # noqa: ANN001
			self.notifys += 1
			return {}

		async def notifystart(self, *_a, **_k):  # noqa: ANN001
			self.notifys += 1
			return {"ret": 0}

		async def aclose(self) -> None:
			return None

	client = FakeClient()
	svc._bridge._client = client  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "BUF1"
	svc._bridge._stop = asyncio.Event()
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await asyncio.wait_for(svc._poll_loop(ch, _DummyRunner()), 2)  # type: ignore[arg-type]
	assert svc._bridge.last_inbound.get("handled") == "command"
	await asyncio.sleep(0.05)
	assert len(sends) == 1


@pytest.mark.asyncio
async def test_connect_error_skips_notify_and_sets_hint(reset_ilink, monkeypatch):
	import channels.ilink.service as svc

	monkeypatch.setattr(svc, "_POLL_CONNECT_SLEEP_S", 0)

	class FakeClient:
		n = 0
		base_url = ""
		notifys = 0

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			self.n += 1
			if self.n <= 2:
				raise httpx.ConnectError("proxy")
			svc._bridge._stop.set()
			return {"ret": 0, "get_updates_buf": buf, "msgs": []}

		async def notifystop(self, *_a, **_k):  # noqa: ANN001
			self.notifys += 1
			return {}

		async def notifystart(self, *_a, **_k):  # noqa: ANN001
			self.notifys += 1
			return {"ret": 0}

		async def reset_poll_http(self) -> None:
			return None

		async def aclose(self) -> None:
			return None

	client = FakeClient()
	svc._bridge._client = client  # type: ignore[assignment]
	svc._bridge._token = "tok"
	svc._bridge._buf = "BUF1"
	svc._bridge._stop = asyncio.Event()
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await asyncio.wait_for(svc._poll_loop(ch, _DummyRunner()), 2)  # type: ignore[arg-type]
	assert client.notifys == 0
	assert svc._bridge.hint == svc._LOGGED_IN_HINT
	assert svc._bridge.last_poll_error is None


def test_rpc_ok_accepts_string_zero():
	from channels.ilink.client import rpc_ok

	assert rpc_ok({"ret": 0, "errcode": 0})
	assert rpc_ok({"ret": "0", "errcode": "0"})
	assert rpc_ok({"ret": 0})
	assert not rpc_ok({"ret": 0, "errcode": 1})
	assert not rpc_ok({"ret": -1})


def test_inbound_queue_keeps_peer_ctx():
	from channels.filehelper.inbound_queue import InboundQueue

	q = InboundQueue()
	assert q.push("a", peer="u1@im.wechat", ctx="ctx-a") == 1
	assert q.push("b", peer="u2@im.wechat", ctx="ctx-b") == 2
	first = q.pop_item()
	assert first is not None
	assert first.text == "a"
	assert first.peer == "u1@im.wechat"
	assert first.ctx == "ctx-a"
	second = q.pop_item()
	assert second is not None
	assert second.peer == "u2@im.wechat"


@pytest.mark.asyncio
async def test_session_expiry_does_not_rewrite_credentials(reset_ilink, tmp_path, monkeypatch):
	from channels.ilink import store
	import channels.ilink.service as svc

	monkeypatch.setattr(store, "credentials_dir", lambda: tmp_path)
	store.save_credentials({"bot_token": "dead", "get_updates_buf": "BUF"})

	class FakeClient:
		base_url = ""

		async def getupdates(self, _token, buf, timeout=40):  # noqa: ANN001
			return {"ret": -14, "errmsg": "session timeout"}

		async def aclose(self) -> None:
			return None

	svc._bridge._client = FakeClient()  # type: ignore[assignment]
	svc._bridge._token = "dead"
	svc._bridge._buf = "BUF"
	svc._bridge._stop = asyncio.Event()
	svc._take_updates_buf({"get_updates_buf": "NEWER"})
	ch = ILinkChannel(_EnqueueRunner(), _RecordingBridge())  # type: ignore[arg-type]
	await svc._poll_loop(ch, _DummyRunner())  # type: ignore[arg-type]
	svc._flush_persist()
	assert svc._bridge._token == ""
	assert not (tmp_path / "credentials.json").is_file()


def test_session_id_for():
	from channels.ilink import SESSION_ID, session_id_for

	uid = "o9cq805KC3TySmv082wL0ROdBeHc@im.wechat"
	assert session_id_for(uid) == f"ilink:{uid}"
	assert session_id_for("") == SESSION_ID
	assert session_id_for(None) == SESSION_ID
	assert session_id_for("ilink:already") == "ilink:already"


@pytest.mark.asyncio
async def test_handle_inbound_passes_reply_peer():
	runner = _EnqueueRunner()
	ch = ILinkChannel(runner, _RecordingBridge())  # type: ignore[arg-type]
	await ch.handle_inbound(
		InboundMessage(
			text="hi",
			session_id="ilink:u@im.wechat",
			sender_id="u@im.wechat",
			raw={"ctx": "ctx-1"},
		)
	)
	assert runner.jobs
	assert runner.jobs[0]["reply_peer"] == "u@im.wechat"
	assert runner.jobs[0]["reply_ctx"] == "ctx-1"
	assert runner.jobs[0]["session_id"] == "ilink:u@im.wechat"


@pytest.mark.asyncio
async def test_two_users_enqueue_different_sessions(reset_ilink):
	import channels.ilink.service as svc

	enqueued = _EnqueueRunner()
	ch = ILinkChannel(enqueued, _RecordingBridge())  # type: ignore[arg-type]
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "a@im.wechat",
			"context_token": "ctx-a",
			"item_list": [{"type": 1, "text_item": {"text": "alpha"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "b@im.wechat",
			"context_token": "ctx-b",
			"item_list": [{"type": 1, "text_item": {"text": "beta"}}],
		},
		ch,
		_DummyRunner(),  # type: ignore[arg-type]
	)
	assert enqueued.texts == [
		("ilink:a@im.wechat", "alpha"),
		("ilink:b@im.wechat", "beta"),
	]


@pytest.mark.asyncio
async def test_busy_does_not_block_other_user(reset_ilink):
	import channels.ilink.service as svc

	class BusyA(_DummyRunner):
		def session_busy(self, sid: str) -> bool:
			return sid == "ilink:a@im.wechat"

	enqueued = _EnqueueRunner()
	ch = ILinkChannel(enqueued, _RecordingBridge())  # type: ignore[arg-type]
	busy_runner = BusyA()
	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "a@im.wechat",
			"context_token": "ctx-a",
			"item_list": [{"type": 1, "text_item": {"text": "alpha"}}],
		},
		ch,
		busy_runner,  # type: ignore[arg-type]
	)
	assert enqueued.texts == []
	assert len(svc._inbound_q) == 1
	queued = svc._inbound_q.pop_item()
	assert queued is not None
	assert queued.session_id == "ilink:a@im.wechat"

	await svc._handle_user_msg(
		{
			"message_type": 1,
			"from_user_id": "b@im.wechat",
			"context_token": "ctx-b",
			"item_list": [{"type": 1, "text_item": {"text": "beta"}}],
		},
		ch,
		busy_runner,  # type: ignore[arg-type]
	)
	assert enqueued.texts == [("ilink:b@im.wechat", "beta")]


def test_inbound_queue_pop_idle_skips_busy_session():
	from channels.filehelper.inbound_queue import InboundQueue

	q = InboundQueue()
	q.push("a", session_id="ilink:a", peer="a")
	q.push("b", session_id="ilink:b", peer="b")
	item = q.pop_idle(lambda sid: sid == "ilink:a")
	assert item is not None
	assert item.text == "b"
	assert item.session_id == "ilink:b"
	left = q.pop_item()
	assert left is not None
	assert left.session_id == "ilink:a"


def test_accepts_stream_session_filters_other_user():
	import channels.ilink.service as svc

	st = svc._st
	prev_stream = st._stream_session_id
	prev_last = st._last_session_id
	try:
		st._stream_session_id = "ilink:a"
		st._last_session_id = "ilink:a"
		assert svc.accepts_stream_session("ilink:a")
		assert not svc.accepts_stream_session("ilink:b")
		assert not svc.accepts_stream_session("filehelper:default")
		st._stream_session_id = ""
		st._last_session_id = ""
		assert svc.accepts_stream_session("ilink:x")
	finally:
		st._stream_session_id = prev_stream
		st._last_session_id = prev_last


def test_push_event_includes_session_id():
	import channels.ilink.service as svc

	m = svc._mirror
	prev = m._events
	prev_seq = m._event_seq
	try:
		m._events = []
		m._event_seq = 0
		rec = svc._push_event("inbound", "hi", session_id="ilink:u1")
		assert rec["session_id"] == "ilink:u1"
		payload = svc.status_payload(omit_jobs=True)
		assert payload["events"][0]["session_id"] == "ilink:u1"
	finally:
		m._events = prev
		m._event_seq = prev_seq


def test_status_stream_session_id_stays_with_active_stream():
	import channels.ilink.service as svc

	st = svc._st
	prev_last = st._last_session_id
	prev_stream = st._stream_session_id
	try:
		st._last_session_id = "ilink:u1"
		st._stream_session_id = "ilink:u1"
		body = svc.status_payload(omit_jobs=True)
		assert body["session_id"] == "ilink:u1"
		assert body["last_session_id"] == "ilink:u1"
		assert body["stream_session_id"] == "ilink:u1"
		st._last_session_id = "ilink:u2"
		body = svc.status_payload(omit_jobs=True)
		assert body["last_session_id"] == "ilink:u2"
		assert body["stream_session_id"] == "ilink:u1"
	finally:
		st._last_session_id = prev_last
		st._stream_session_id = prev_stream

