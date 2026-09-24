"""适配器 → ``diagnostics.capture`` 的接线（三个模型客户端的唯一调用点）。

三个适配器无共同基类，各自在 body 定型后、交给 HTTP 客户端前调一次
``capture_body``，拿到回挂响应身份用的句柄；状态码 / 厂商请求 id 可见处调
``capture_response``。

铁律落在代码形状上：

- 开关关掉时这里只有一次属性读取 + ``capture_enabled`` 判断，不序列化、不哈希。
- 交给捕获层的永远是原 body（捕获层自己深拷贝），本模块不改 body。
- 认证头永不入捕获层：只传 JSON body，响应头里只取 request id 一个字段。
- 捕获层任何异常（含 import 失败）都在这里吞掉——观察器不得改变模型可见消息，
  也不得拖死任务。
"""

from __future__ import annotations

import logging
from typing import Any

# 厂商在响应头里回带的请求 id（各家命名并存）。取不到就留空，绝不自行编造。
_REQUEST_ID_HEADERS = ("request-id", "x-request-id")


def _s(value: Any) -> str:
	return str(value if value is not None else "").strip()


def _context() -> Any:
	try:
		from engine.workspace_context import get_execution_context

		return get_execution_context()
	except Exception:  # noqa: BLE001 — 上下文不可用只算缺身份，不影响发送
		return None


def _session_id(client: Any) -> str:
	"""客户端注入值优先；缺失才读执行上下文（关闭捕获时不必多读一次 turn）。"""
	sid = _s(getattr(client, "_session_id", ""))
	if sid:
		return sid
	ctx = _context()
	return _s(getattr(ctx, "session_id", "")) if ctx is not None else ""


def _turn_id() -> str:
	"""沿用现状 ``trace_id == turn_id``（见 diagnostics.identity.row_turn_id）。"""
	ctx = _context()
	return _s(getattr(ctx, "trace_id", "")) if ctx is not None else ""


def _attempt(client: Any) -> int:
	"""与用量账本同一口径：``_meta_attempt`` 缺失 / 非数都算第 1 次尝试。"""
	try:
		return int(getattr(client, "_meta_attempt", 1) or 1)
	except (TypeError, ValueError):
		return 1


def _provider_request_id(headers: Any) -> str:
	"""只读请求 id 头；httpx.Headers / email.message.Message / dict 都支持 get。"""
	get = getattr(headers, "get", None)
	if not callable(get):
		return ""
	for name in _REQUEST_ID_HEADERS:
		try:
			value = get(name)
		except Exception:  # noqa: BLE001 — 头部实现不可预知，读不到就算缺
			return ""
		if _s(value):
			return _s(value)
	return ""


def _http_status(value: Any) -> int | None:
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def capture_body(
	client: Any,
	*,
	provider: str,
	model: str,
	body: Any,
) -> dict[str, Any] | None:
	"""发送前捕获最终请求体，返回响应身份回挂句柄；未开启 / 失败返回 ``None``。"""
	try:
		sid = _session_id(client)
		if not sid:
			return None
		from diagnostics.capture import capture_enabled, capture_request

		if not capture_enabled(sid):
			return None
		request_id = _s(getattr(client, "_meta_request_id", ""))
		attempt = _attempt(client)
		row = capture_request(
			session_id=sid,
			turn_id=_turn_id(),
			model_request_id=request_id,
			attempt=attempt,
			provider=_s(provider),
			model=_s(model),
			body=body,
		)
		if not row:
			return None
		return {
			"session_id": sid,
			"model_request_id": request_id,
			"attempt": attempt,
			"body_hash": _s(row.get("body_hash")),
		}
	except Exception:  # noqa: BLE001 — 观察器故障不得影响发送
		logging.getLogger(__name__).debug("request capture hook failed", exc_info=True)
		return None


def capture_response(
	handle: dict[str, Any] | None,
	*,
	http_status: Any = None,
	headers: Any = None,
	usage: Any = None,
) -> None:
	"""把响应身份（状态码 + 厂商请求 id）挂到同一次尝试的捕获上；无句柄即静默。"""
	if not handle:
		return
	try:
		from diagnostics.capture import record_response

		record_response(
			session_id=_s(handle.get("session_id")),
			model_request_id=_s(handle.get("model_request_id")),
			attempt=handle.get("attempt"),
			body_hash=_s(handle.get("body_hash")),
			provider_request_id=_provider_request_id(headers),
			http_status=_http_status(http_status),
			usage=usage if isinstance(usage, dict) else None,
		)
	except Exception:  # noqa: BLE001
		logging.getLogger(__name__).debug("response identity hook failed", exc_info=True)


__all__ = ["capture_body", "capture_response"]
