"""HTTP helpers for sessions / attach."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx


class PathIdError(ValueError):
	"""一个身份键不可能指向它所命名的资源（会被拼进 URL 路径段）。"""


class ApiError(RuntimeError):
	"""服务端的拒绝：带 HTTP 状态码与服务端自己给出的原因原文。"""

	def __init__(self, status: int, detail: str = "") -> None:
		self.status = status
		self.detail = detail
		super().__init__(f"HTTP {status}: {detail}" if detail else f"HTTP {status}")


#: 镜像 ``server/routers/sessions.py::_ID_ALLOWED_RE``。CLI 把 session_id 直接插进
#: URL 路径段：``a/b`` 会打到 ``DELETE /v1/sessions/{id}/agents/{aid}/inbox/{iid}``
#: （删掉另一个资源），``../..`` 会整个逃出 ``/v1/sessions`` 前缀。百分号编码挡不住
#: ——ASGI 在路由前就解码路径。服务端对同一字符集 422，所以本地先拒不会挡掉任何
#: 服务端本来会接受的 id。
_ID_SEGMENT_RE = re.compile(r"[A-Za-z0-9._:\-]+\Z")
_MAX_ID_CHARS = 128


def require_path_segment(value: Any, *, field: str = "session_id") -> str:
	"""校验会被拼进 URL 路径段的身份键；歧义形态一律抛 :class:`PathIdError`。

	只做「能否安全拼进路径」这一件事。会话 id 的固定点碰撞（``victim.`` 与
	``victim`` 在磁盘上同名）仍由服务端的 ``_require_stable_id`` 裁决 ⇒ CLI 把它的
	422 detail 原样转述（见 ``_response_body``），不在本地复制第二套权威判据。
	"""
	raw = "" if value is None else str(value)
	if not raw.strip():
		raise PathIdError(f"{field} is blank")
	if raw != raw.strip():
		raise PathIdError(f"{field} has leading or trailing whitespace")
	if len(raw) > _MAX_ID_CHARS:
		raise PathIdError(f"{field} exceeds {_MAX_ID_CHARS} characters")
	if not _ID_SEGMENT_RE.match(raw):
		raise PathIdError(f"{field} contains characters outside [A-Za-z0-9._:-]")
	return raw


def _response_body(r: httpx.Response) -> str:
	"""服务端拒绝的原因原文（尽力取 detail/error/message）。"""
	try:
		raw = r.read().decode(errors="replace")
	except Exception:  # noqa: BLE001
		return ""
	text = raw.strip()
	if not text:
		return ""
	try:
		obj = json.loads(text)
	except Exception:  # noqa: BLE001
		return text[:300]
	if isinstance(obj, dict):
		for key in ("detail", "error", "message"):
			val = obj.get(key)
			if isinstance(val, str) and val.strip():
				return val.strip()[:300]
	return text[:300]


def _ensure_ok(r: httpx.Response) -> None:
	"""4xx/5xx 转成带原因的错误——不静默降级成空结果。"""
	if r.status_code >= 400:
		raise ApiError(r.status_code, _response_body(r))


def make_client(base_url: str, api_key: str = "", timeout: float | None = 60.0) -> httpx.Client:
	headers: dict[str, str] = {"Accept": "application/json"}
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"
	return httpx.Client(
		base_url=base_url.rstrip("/"),
		headers=headers,
		timeout=timeout,
	)


def list_sessions(client: httpx.Client) -> list[dict[str, Any]]:
	r = client.get("/v1/sessions")
	_ensure_ok(r)
	data = r.json()
	if isinstance(data, dict):
		if data.get("ok") is False:
			raise ApiError(r.status_code, str(data.get("detail") or "server reported ok=false"))
		if "sessions" not in data:
			# 认不出的响应体 ≠ 「一个会话都没有」：说不知道，别说零。
			raise ApiError(r.status_code, "server response has no 'sessions' field")
		sessions = data.get("sessions")
	else:
		sessions = data
	if not isinstance(sessions, list):
		raise ApiError(r.status_code, "server response 'sessions' is not a list")
	return list(sessions)


def delete_session(client: httpx.Client, session_id: str) -> dict[str, Any]:
	require_path_segment(session_id)
	r = client.delete(f"/v1/sessions/{session_id}")
	_ensure_ok(r)
	data = r.json() if r.content else {"ok": True}
	return data if isinstance(data, dict) else {"ok": True, "raw": data}


def get_messages(client: httpx.Client, session_id: str) -> dict[str, Any]:
	require_path_segment(session_id)
	r = client.get(f"/v1/sessions/{session_id}/messages")
	_ensure_ok(r)
	data = r.json()
	return data if isinstance(data, dict) else {"messages": data}


def resolve_permission_http(
	client: httpx.Client,
	request_id: str,
	*,
	approved: bool,
	choice: str | None = None,
) -> bool:
	body: dict[str, Any] = {
		"request_id": request_id,
		"approved": approved,
		"actor": "cli",
	}
	if choice:
		body["outcome"] = choice
	r = client.post("/v1/permission/resolve", json=body)
	r.raise_for_status()
	return bool(r.json().get("ok", True))


def resolve_ask_http(client: httpx.Client, request_id: str, answer: str) -> bool:
	r = client.post(
		"/v1/ask/resolve",
		json={"request_id": request_id, "answer": answer, "actor": "cli"},
	)
	r.raise_for_status()
	return bool(r.json().get("ok", True))


def resolve_plan_http(client: httpx.Client, request_id: str, approved: bool) -> bool:
	r = client.post(
		f"/v1/plan/{request_id}/approve",
		json={"approved": approved, "actor": "cli"},
	)
	r.raise_for_status()
	return bool(r.json().get("ok", True))


def interrupt_http(client: httpx.Client, session_id: str) -> bool:
	r = client.post("/v1/interrupt", json={"session_id": session_id})
	r.raise_for_status()
	return bool(r.json().get("ok", True))
