"""iLink 镜像状态：事件环、流文本、状态载荷组装（基于 ChannelMirror）。

从 service.py 拆出：本模块自持 mirror 单例（delta_extra 依赖 _mirror_sid，
故 mirror 不放在 _state.py 以免循环导入）。

可变全局一律通过 ``_st.`` 属性访问：``from ._state import X`` 对
str/int 是值拷贝，跨模块写入会脱节。
"""

from __future__ import annotations

import time
from typing import Any

import channels.ilink._state as _st
from channels.ilink import SESSION_ID
from channels.ilink import broadcast as il_broadcast
from channels.jobs import JobStore
from channels.mirror import ChannelMirror


def _mirror_sid() -> str:
	return _st._stream_session_id or _st._last_session_id or SESSION_ID


_mirror = ChannelMirror(
	broadcast=il_broadcast,
	session_prefix="ilink:",
	delta_extra=lambda: {
		"session_id": _mirror_sid(),
		"stream_session_id": _st._stream_session_id or _mirror_sid(),
	},
)


def accepts_stream_session(session_id: str) -> bool:
	"""当前桌面镜像只收这个 iLink session 的 delta/tool。"""
	sid = (session_id or "").strip()
	if not sid.startswith("ilink:"):
		return False
	cur = _st._stream_session_id or _st._last_session_id
	if not cur:
		return True
	return sid == cur


def _cancel_stream_flush() -> None:
	_mirror._cancel_stream_flush()


def _publish_stream(*, reset: bool) -> None:
	_mirror._publish_stream(reset=reset)


def _flush_stream() -> None:
	_mirror._flush_stream()


def _broadcast_stream(*, reset: bool = False) -> None:
	"""reset 立刻推；普通 delta 合并到约 30Hz。"""
	_mirror.broadcast_stream(reset=reset)


def _push_event(
	kind: str,
	text: str,
	*,
	command: str | None = None,
	session_id: str = "",
	**extra: Any,
) -> dict[str, Any]:
	return _mirror.push_event(
		kind,
		text,
		command=command,
		session_id=(session_id or "").strip() or _mirror_sid(),
		**extra,
	)


def events_since(after_id: str = "") -> list[dict[str, Any]]:
	return _mirror.events_since(after_id)


def _state_payload() -> dict[str, Any]:
	b = _st._bridge
	return {
		"state": b.state,
		"logged_in": b.logged_in,
		"has_qr": b.qr_png() is not None,
		"qr_rev": b.qr_rev,
		"error": b.error,
		"hint": b.hint,
		"session_id": _st._last_session_id or SESSION_ID,
		"last_session_id": _st._last_session_id or SESSION_ID,
		"stream_session_id": _st._stream_session_id,
		"streaming": _mirror.stream_active,
		"channel": "ilink",
		"last_poll_error": b.last_poll_error,
		"poll_timeouts": b.poll_timeouts,
	}


def _broadcast_state() -> None:
	payload = _state_payload()
	if _mirror.stream_active:
		payload["stream_len"] = len(_mirror._stream_text)
		if _mirror._stream_status:
			payload["stream_status"] = _mirror._stream_status
	il_broadcast.publish("state", payload)


def status_payload(
	store: JobStore | None = None,
	*,
	after_id: str = "",
	omit_jobs: bool = False,
	stream_from: int | None = None,
) -> dict[str, object]:
	b = _st._bridge
	payload: dict[str, object] = {
		"state": b.state,
		"logged_in": b.logged_in,
		"has_qr": b.qr_png() is not None,
		"qr_rev": b.qr_rev,
		"error": b.error,
		"hint": b.hint,
		"session_id": _st._last_session_id or SESSION_ID,
		"last_session_id": _st._last_session_id or SESSION_ID,
		"stream_session_id": _st._stream_session_id,
		"events": events_since(after_id),
		"streaming": _mirror.stream_active,
		"channel": "ilink",
		"poll_alive": bool(b._loop_task is not None and not b._loop_task.done()),
		"last_poll_msgs": b.last_poll_msgs,
		"last_poll_ret": b.last_poll_ret,
		"last_poll_error": b.last_poll_error,
		"poll_timeouts": b.poll_timeouts,
		"last_inbound": b.last_inbound,
		"event_n": len(_mirror._events),
		"inbound_rev": 5,
		"has_peer": bool(b.peer_id),
		"has_context": bool(b.context_token),
		"has_channel": _st._channel is not None,
		"poll_wait_s": (
			round(time.monotonic() - b.poll_started_at, 1)
			if b.poll_started_at
			else 0
		),
	}
	if not omit_jobs:
		jobs: list[dict[str, object]] = []
		if store is not None:
			jobs = [
				r.to_public()
				for r in store.recent(8, session_id=_st._last_session_id or None)
			]
		payload["recent_jobs"] = jobs
	if _mirror.stream_active:
		payload.update(_mirror.stream_payload_section(stream_from))
	return payload