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


def _receipt(r: httpx.Response, what: str) -> dict[str, Any]:
	"""200 只是 HTTP 层：这些写操作端点在**信封里**用 ok 表达"没接受"。

	读不出的三种形态（没有正文 / 正文不是 JSON 对象 / 换代理回的 HTML）以前都会走
	``bool(r.json().get("ok", True))`` 的默认值 True ⇒ 终端把一次没送达的放行念成
	「✓ allowed」。这里把它们变成错误，不猜。
	"""
	try:
		data = r.json()
	except Exception as exc:  # noqa: BLE001 — 没有正文 / 非 JSON 都算读不出
		raise ApiError(r.status_code, f"{what}：回执没有可读的 JSON 正文，无法确认服务端是否接受") from exc
	if not isinstance(data, dict):
		raise ApiError(r.status_code, f"{what}：回执不是对象，无法确认服务端是否接受")
	return data


def _confirmed(r: httpx.Response, what: str) -> bool:
	"""只有 ``ok is True`` 才算成功；``ok:false`` 带上服务端给的 reason 抛出。"""
	data = _receipt(r, what)
	ok = data.get("ok")
	if ok is True:
		return True
	if "ok" not in data:
		raise ApiError(r.status_code, f"{what}：回执里没有 ok 字段，无法确认服务端是否接受")
	if ok is not False:
		# 缺字段与"字段在但说不出真假"都不是服务端说过的话，不能折成任何一种。
		raise ApiError(r.status_code, f"{what}：回执里的 ok 不是布尔，无法确认服务端是否接受")
	reason = str(data.get("reason") or "").strip()
	detail = str(data.get("detail") or "").strip()
	raise ApiError(r.status_code, f"{what}：{reason or detail or '服务端未接受这次决议'}")


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
	# 删除是隐私动作：空正文或没有 ok 的回执都不能折算成"删干净了"。
	data = _receipt(r, "删除会话")
	if not isinstance(data.get("ok"), bool):
		raise ApiError(r.status_code, "删除会话：回执里没有 ok 字段，无法确认服务端删掉了什么")
	return data


def get_messages(client: httpx.Client, session_id: str) -> dict[str, Any]:
	require_path_segment(session_id)
	r = client.get(f"/v1/sessions/{session_id}/messages")
	_ensure_ok(r)
	data = _receipt(r, "读取会话消息")
	if not isinstance(data.get("messages"), list):
		# 与 list_sessions 同一条理由：认不出的回执 ≠ 这个会话没有消息。
		raise ApiError(r.status_code, "server response has no 'messages' list")
	return data


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
	_ensure_ok(r)
	return _confirmed(r, "权限决议")


def resolve_ask_http(client: httpx.Client, request_id: str, answer: str) -> bool:
	r = client.post(
		"/v1/ask/resolve",
		json={"request_id": request_id, "answer": answer, "actor": "cli"},
	)
	_ensure_ok(r)
	return _confirmed(r, "提问作答")


def resolve_plan_http(client: httpx.Client, request_id: str, approved: bool) -> bool:
	r = client.post(
		f"/v1/plan/{request_id}/approve",
		json={"approved": approved, "actor": "cli"},
	)
	_ensure_ok(r)
	return _confirmed(r, "计划批准")


def interrupt_http(client: httpx.Client, session_id: str) -> bool:
	"""True=服务端确认停止；False=服务端没有在跑的回合（幂等 no-op，不是失败）。

	读不出（缺 ok / 正文不是对象）抛 :class:`ApiError`：把"没确认"和"确认了但没东西可停"
	混成同一个 False，等于让调用方拿猜测填空白。
	"""
	r = client.post("/v1/interrupt", json={"session_id": session_id})
	_ensure_ok(r)
	data = _receipt(r, "停止会话")
	if "ok" not in data:
		raise ApiError(r.status_code, "停止会话：回执里没有 ok 字段，无法确认服务端是否收到")
	return data["ok"] is True
