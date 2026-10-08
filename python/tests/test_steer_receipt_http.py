"""忙时受理体的 HTTP 门（对齐 Codex：queued_messages vs TurnSteer 两种回执）。

事故原型：引导回执不带客户端消息 id ⇒ 前端只能把它当普通排队，生成一张
``queue_id`` 为空、DELETE 必 400 的删不掉幽灵卡；反向（把引导当排队）则让用户
以为本轮就能看到。受理体是 wires 口径，故在真 HTTP 路由上核，不靠单元测试自证。

键集的**唯一声明面**在 ``server/stream_contract.ACCEPT_EVENT_KEYS``，并由
``gui/src/lib/api/streamContract.test.ts`` 与前端读取的键双向对账。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import server.app as app_mod  # noqa: E402
from server.stream_contract import ACCEPT_EVENT_KEYS  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
	# 引导入队会写私有 inbox 状态；测试必须隔离会话目录，别碰真实 ~/.xeyo
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	from engine.t_now_steer import clear as _clear_steer

	_clear_steer()
	yield
	_clear_steer()


def _post_busy(*, sid: str, steer: bool, queue: bool, mid: str = "m-client-1"):
	c = TestClient(app_mod.app)
	lease = app_mod._pool.try_begin(sid)
	assert lease is not None, "测试前置：会话租约应可持有（=正忙）"
	try:
		r = c.post(
			"/v1/chat/completions",
			headers={"Authorization": "Bearer test-key"},
			json={
				"model": "deepseek-chat",
				"stream": True,
				"session_id": sid,
				"steer_if_busy": steer,
				"queue_if_busy": queue,
				"messages": [{"role": "user", "content": "先别动文件", "id": mid}],
			},
		)
	finally:
		app_mod._pool.end(sid, lease)
	return r


def test_steer_receipt_carries_client_message_id() -> None:
	r = _post_busy(sid="steer-receipt-1", steer=True, queue=True)
	assert r.status_code == 202, r.text
	body = r.json()
	assert set(body) == set(ACCEPT_EVENT_KEYS["steered"]), body
	assert body["steered"] is True
	assert body["delivery"] == "boundary"
	# 引导回执继续以客户端 message id 标识，必须原样带回来
	assert body["message_id"] == "m-client-1"


def test_queued_receipt_carries_queue_id_and_position() -> None:
	r = _post_busy(sid="steer-receipt-2", steer=False, queue=True)
	assert r.status_code == 202, r.text
	body = r.json()
	assert set(body) == set(ACCEPT_EVENT_KEYS["queued"]), body
	assert body["delivery"] == "after_turn"
	assert str(body["queue_id"]).strip(), "排队回执必须给出可撤销的 queue_id"
	assert body["position"] == 1


@pytest.mark.parametrize("steer", [False, True])
def test_retried_busy_input_keeps_one_pending_owner(steer) -> None:
	sid = f"retry-busy-input-{steer}"
	first = _post_busy(sid=sid, steer=steer, queue=True)
	second = _post_busy(sid=sid, steer=steer, queue=True)
	assert first.status_code == second.status_code == 202
	assert first.json() == second.json()
	from server.inbox_registry import get_inbox_registry
	assert len(get_inbox_registry().snapshot(sid)["items"]) == 1


def test_side_session_steer_is_refused_not_silently_downgraded() -> None:
	"""引导在 side 会话不支持：明确 409，绝不静默降级成"回合结束后投"。"""
	c = TestClient(app_mod.app)
	sid = "side-steer-receipt"
	lease = app_mod._pool.try_begin(sid)
	assert lease is not None
	try:
		r = c.post(
			"/v1/chat/completions",
			headers={"Authorization": "Bearer test-key"},
			json={
				"model": "deepseek-chat",
				"stream": True,
				"session_id": sid,
				"side": True,
				"steer_if_busy": True,
				"queue_if_busy": True,
				"messages": [{"role": "user", "content": "插一句", "id": "m-2"}],
			},
		)
	finally:
		app_mod._pool.end(sid, lease)
	assert r.status_code == 409
	assert r.json()["error"]["type"] == "steer_unsupported_side"


def test_steer_delivered_frame_reaches_the_stream(monkeypatch) -> None:
	"""端到端：队列里已有引导 ⇒ 本轮边界投进历史，并真的发出 steer_delivered 帧。

	这条是回执的另半边：GUI 靠 ``message_ids`` 撤掉 inbox 卡。帧只声明不发出，
	前端就会永远挂着一条"已排队"卡——名称对账门看不见这种缺陷。
	"""
	from engine.t_now_steer import push as _push

	monkeypatch.setenv("XEYO_ALLOW_FAKE_MODEL", "1")
	sid = "steer-frame-http"
	assert _push(sid, "插一句：先只看不动", message_id="m-9") is True

	c = TestClient(app_mod.app)
	r = c.post(
		"/v1/chat/completions",
		headers={"Authorization": "Bearer test-key"},
		json={
			"model": "fake",
			"provider": "fake",
			"stream": True,
			"session_id": sid,
			"messages": [{"role": "user", "content": "把登录页改掉", "id": "m-main"}],
		},
	)
	assert r.status_code == 200, r.text
	body = r.text
	assert '"type": "steer_delivered"' in body or '"type":"steer_delivered"' in body, (
		"边界投递必须有回执帧：" + body[-800:]
	)
	assert "m-9" in body, "回执必须带客户端消息 id，否则前端撤不掉卡"
