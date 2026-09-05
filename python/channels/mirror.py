"""通道镜像公共状态：事件环形缓冲、流文本 30Hz 合并广播、工具事件。

ilink 与 filehelper 两个 service 曾各写一份几乎相同的实现（_push_event /
events_since / _broadcast_stream / _emit_ui_tool / status_payload 的流段）。
本类收敛公共部分，差异（微信协议、poll 状态、session 游标）留在各 service。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

_PREFIX_EVENT = "ev-"


class ChannelMirror:
	"""一个通道的 UI 镜像状态机（事件 + 流 + 工具事件）。

	- ``broadcast``：模块级广播对象（``publish(event, data)`` + ``format_sse``）。
	- ``session_prefix``：仅接受该前缀 session 的流回调（如 "ilink:"）。
	"""

	def __init__(
		self,
		*,
		broadcast: Any,
		session_prefix: str = "",
		stream_hz: float = 30.0,
		max_events: int = 80,
		delta_extra: Callable[[], dict[str, Any]] | None = None,
	) -> None:
		self._broadcast = broadcast
		self._session_prefix = (session_prefix or "").strip()
		self._stream_hz = max(1.0, float(stream_hz))
		self._max_events = max(16, int(max_events))
		# 通道特有字段（如 ilink 的 session_id / stream_session_id）注入器。
		self._delta_extra = delta_extra
		self._events: list[dict[str, Any]] = []
		self._event_seq = 0
		self._stream_active = False
		self._stream_text = ""
		self._stream_status = ""
		self._stream_tools: list[dict[str, Any]] = []
		self._tool_seq = 0
		self._stream_flush_handle: asyncio.TimerHandle | None = None
		self._state_builder: Callable[[], dict[str, Any]] | None = None

	def set_state_builder(self, builder: Callable[[], dict[str, Any]] | None) -> None:
		"""status_payload 之外的 state 快照（/state 广播用），由 service 注入。"""
		self._state_builder = builder

	# ==================== 事件 ====================

	def push_event(
		self,
		kind: str,
		text: str,
		*,
		command: str | None = None,
		session_id: str = "",
		**extra: Any,
	) -> dict[str, Any]:
		self._event_seq += 1
		rec: dict[str, Any] = {
			"id": f"ev-{self._event_seq}",
			"kind": kind,
			"text": text,
			"ts": time.time(),
			"command": command,
			"session_id": (session_id or "").strip(),
		}
		rec.update(extra)
		self._events.append(rec)
		if len(self._events) > self._max_events:
			del self._events[: self._max_events // 2]
		self._broadcast.publish("event", rec)
		return rec

	def events_since(self, after_id: str = "") -> list[dict[str, Any]]:
		if not after_id:
			return list(self._events)
		idx = next((i for i, e in enumerate(self._events) if e["id"] == after_id), None)
		if idx is not None:
			return self._events[idx + 1 :]
		# 游标被裁掉时不能返回空，否则 HTTP 兜底再也收不到新事件。
		if after_id.startswith(_PREFIX_EVENT):
			try:
				n = int(after_id[len(_PREFIX_EVENT) :])
				out: list[dict[str, Any]] = []
				seen: list[int] = []
				for e in self._events:
					eid = str(e.get("id") or "")
					if eid.startswith(_PREFIX_EVENT):
						try:
							en = int(eid[len(_PREFIX_EVENT) :])
							seen.append(en)
							if en > n:
								out.append(e)
						except ValueError:
							out.append(e)
					else:
						out.append(e)
				# 进程重启后序号从 1 再起，前端还拿着旧的 ev-N，必须整表重放。
				if not out and self._events and seen and n > max(seen):
					return list(self._events)
				return out
			except ValueError:
				pass
		return list(self._events)

	# ==================== 流 ====================

	@property
	def stream_active(self) -> bool:
		return self._stream_active

	def reset_stream(self) -> None:
		"""回合开始/结束时清空流状态并广播复位帧。"""
		self._cancel_stream_flush()
		self._stream_active = False
		self._stream_text = ""
		self._stream_status = ""
		self._stream_tools = []
		self._publish_stream(reset=True)

	def begin_stream(self) -> None:
		self._stream_active = True
		self._stream_text = ""
		self._stream_status = "thinking…"
		self._stream_tools = []
		self._publish_stream(reset=True)

	def append_delta(self, chunk: str, status: str = "") -> None:
		self._stream_text += chunk
		self._stream_status = status
		self._broadcast_stream()

	def set_status(self, status: str) -> None:
		self._stream_status = status
		self._broadcast_stream()

	def _publish_stream(self, *, reset: bool) -> None:
		payload: dict[str, Any] = {
			"text": self._stream_text,
			"len": len(self._stream_text),
			"status": self._stream_status,
			"streaming": self._stream_active,
			"reset": reset,
		}
		if self._delta_extra is not None:
			try:
				payload.update(self._delta_extra() or {})
			except Exception:
				pass
		self._broadcast.publish("delta", payload)

	def _broadcast_stream(self, *, reset: bool = False) -> None:
		"""reset 立刻推；普通 delta 合并到约 stream_hz 频率。"""
		if reset:
			self._cancel_stream_flush()
			self._publish_stream(reset=True)
			return
		if self._stream_flush_handle is not None:
			return
		try:
			loop = asyncio.get_running_loop()
		except RuntimeError:
			self._publish_stream(reset=False)
			return
		self._stream_flush_handle = loop.call_later(
			1.0 / self._stream_hz, self._flush_stream
		)

	def _flush_stream(self) -> None:
		self._stream_flush_handle = None
		self._publish_stream(reset=False)

	def _cancel_stream_flush(self) -> None:
		if self._stream_flush_handle is not None:
			self._stream_flush_handle.cancel()
			self._stream_flush_handle = None

	def accepts_session(self, session_id: str) -> bool:
		"""当前只镜像本通道 session 前缀的流。"""
		sid = (session_id or "").strip()
		if not sid.startswith(self._session_prefix):
			return False
		return True

	# ==================== 工具事件 ====================

	def emit_ui_tool(
		self,
		kind: str,
		*,
		name: str,
		session_id: str = "",
		input: dict[str, Any] | None = None,
		output: str = "",
		is_error: bool = False,
	) -> dict[str, Any]:
		self._cancel_stream_flush()
		self._publish_stream(reset=False)
		self._tool_seq += 1
		rec: dict[str, Any] = {
			"id": f"tool-{self._tool_seq}",
			"kind": kind,
			"name": name,
			"session_id": session_id,
		}
		if kind == "tool_call":
			rec["input"] = input or {}
			self._stream_status = f"使用 {name}…"
			self._stream_text = ""
		else:
			rec["output"] = output
			rec["is_error"] = is_error
			self._stream_status = ""
		self._stream_tools.append(rec)
		self._broadcast.publish("tool", rec)
		self._publish_stream(reset=True)
		return rec

	# ==================== 状态载荷的流段 ====================

	def stream_payload_section(
		self,
		stream_from: int | None = None,
	) -> dict[str, Any]:
		"""status_payload 的公共流段：streaming/len/status/text/tools。"""
		payload: dict[str, Any] = {}
		if not self._stream_active:
			return payload
		full = self._stream_text
		payload["stream_len"] = len(full)
		if stream_from is None:
			payload["stream_text"] = full
		elif stream_from < 0 or stream_from > len(full):
			payload["stream_reset"] = True
			payload["stream_text"] = full
		else:
			payload["stream_text"] = full[stream_from:]
		if self._stream_status:
			payload["stream_status"] = self._stream_status
		if self._stream_tools:
			payload["stream_tools"] = list(self._stream_tools)
		return payload

	# ==================== 重置 ====================

	def reset_data(self) -> None:
		"""测试/stop 用：清空全部数据态（不碰 asyncio 原语——本类无原语）。"""
		self._cancel_stream_flush()
		self._events = []
		self._event_seq = 0
		self._stream_active = False
		self._stream_text = ""
		self._stream_status = ""
		self._stream_tools = []
		self._tool_seq = 0

	def json_dumps(self, payload: dict[str, Any]) -> str:
		return json.dumps(payload, ensure_ascii=False)