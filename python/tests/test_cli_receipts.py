"""CLI 的写操作回执：200 不等于服务端接受了。

cli/http_api.py 里这四个写操作曾经是 ``bool(r.json().get("ok", True))`` ——
默认值是 True，于是"缺 ok / 空正文 / 代理回的数组"全被念成成功，
而 cli/interact.py 在发请求之前就已经打印 ``✓ allowed``。
真实语义（server/routers/control.py）是信封里给 ``ok`` 与 ``reason``：
already_resolved / no_such_request 都是"这次决议没有被接受"。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cli import http_api
from cli.http_api import ApiError

_NO_BODY = object()


class _Resp:
	"""最小 httpx.Response 替身：只要 status_code / read() / json() 三件事。"""

	def __init__(self, payload: Any = None, *, status: int = 200, raw: bytes | None = None) -> None:
		self.status_code = status
		self._payload = payload
		if raw is not None:
			self._body = raw
		elif payload is _NO_BODY:
			self._body = b""
		else:
			self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

	def read(self) -> bytes:
		return self._body

	@property
	def content(self) -> bytes:
		return self._body

	def json(self) -> Any:
		if self._payload is _NO_BODY:
			raise ValueError("no body")
		return self._payload

	def raise_for_status(self) -> None:  # pragma: no cover - 现在应走 _ensure_ok
		if self.status_code >= 400:
			raise AssertionError("写操作应经 _ensure_ok 转成带原因的 ApiError")


class _Client:
	def __init__(self, resp: _Resp) -> None:
		self.resp = resp
		self.calls: list[tuple[str, str, Any]] = []

	def post(self, url: str, *, json: Any = None) -> _Resp:
		self.calls.append(("POST", url, json))
		return self.resp

	def get(self, url: str) -> _Resp:
		self.calls.append(("GET", url, None))
		return self.resp

	def delete(self, url: str) -> _Resp:
		self.calls.append(("DELETE", url, None))
		return self.resp


def _raises(client: _Client, fn) -> str:
	with pytest.raises(ApiError) as e:
		fn(client)
	return str(e.value)


def test_permission_receipt_ok_true_is_success() -> None:
	client = _Client(_Resp({"ok": True, "request_id": "r1", "grant_id": ""}))
	assert http_api.resolve_permission_http(client, "r1", approved=True, choice="allow") is True


def test_permission_receipt_ok_false_carries_server_reason() -> None:
	client = _Client(_Resp({"ok": False, "request_id": "r1", "reason": "already_resolved"}))
	text = _raises(client, lambda c: http_api.resolve_permission_http(c, "r1", approved=False))
	assert "already_resolved" in text


def test_missing_ok_in_200_is_not_reported_as_success() -> None:
	# 旧写法 .get("ok", True) 在这一格会返回 True。
	for payload in ({"request_id": "r1"}, {}, {"ok": None}, {"ok": "true"}):
		client = _Client(_Resp(payload))
		text = _raises(client, lambda c: http_api.resolve_permission_http(c, "r1", approved=True))
		assert "无法确认" in text, payload


def test_unreadable_body_raises_instead_of_crashing() -> None:
	client = _Client(_Resp(_NO_BODY))
	assert "无法确认" in _raises(client, lambda c: http_api.resolve_permission_http(c, "r1", approved=True))
	# 反代/登录页常见的非对象正文
	client = _Client(_Resp([{"ok": True}]))
	assert "不是对象" in _raises(client, lambda c: http_api.resolve_ask_http(c, "r1", "a"))


def test_ask_and_plan_read_the_envelope_too() -> None:
	assert http_api.resolve_ask_http(_Client(_Resp({"ok": True})), "r1", "答案") is True
	assert http_api.resolve_plan_http(_Client(_Resp({"ok": True})), "t1", True) is True
	text = _raises(_Client(_Resp({"ok": False, "reason": "no_such_request"})), lambda c: http_api.resolve_ask_http(c, "r1", "x"))
	assert "no_such_request" in text
	text = _raises(_Client(_Resp({"ok": False})), lambda c: http_api.resolve_plan_http(c, "t1", False))
	assert "服务端未接受" in text


def test_interrupt_separates_nothing_running_from_unreadable() -> None:
	assert http_api.interrupt_http(_Client(_Resp({"ok": True})), "s1") is True
	# 幂等 no-op：服务端没有在运行的回合 —— 不是失败，也不该抛错。
	assert http_api.interrupt_http(_Client(_Resp({"ok": False})), "s1") is False
	text = _raises(_Client(_Resp({"detail": "queued"})), lambda c: http_api.interrupt_http(c, "s1"))
	assert "没有 ok 字段" in text


def test_4xx_carries_the_server_reason_text() -> None:
	client = _Client(_Resp(None, status=422, raw=json.dumps({"detail": "outcome must be allow / deny / remind"}).encode("utf-8")))
	text = _raises(client, lambda c: http_api.resolve_permission_http(c, "r1", approved=True, choice="deny-all"))
	assert "422" in text and "outcome must be" in text


def test_delete_session_rejects_empty_body_as_success() -> None:
	text = _raises(_Client(_Resp(_NO_BODY)), lambda c: http_api.delete_session(c, "s1"))
	assert "无法确认" in text
	# 回执里有 removed 但没有 ok：也不能折算成"删干净了"。
	text = _raises(
		_Client(_Resp({"session_id": "s1", "removed": ["a.jsonl"]})),
		lambda c: http_api.delete_session(c, "s1"),
	)
	assert "ok" in text and "无法确认" in text
	# 服务端"没删干净"必须原样交给调用方判断（sessions_cmd 会读 ok）
	data = http_api.delete_session(_Client(_Resp({"ok": False, "removal_errors": [{"path": "p", "error": "busy"}]})), "s1")
	assert data["ok"] is False


def test_get_messages_without_a_list_is_not_no_messages() -> None:
	text = _raises(_Client(_Resp({"session_id": "s1"})), lambda c: http_api.get_messages(c, "s1"))
	assert "no 'messages' list" in text
	assert http_api.get_messages(_Client(_Resp({"session_id": "s1", "messages": []})), "s1")["messages"] == []
