"""工具执行中的进度旁路（ContextVar）。

编排层在 ``_run_one_tool`` 里挂上 sink，工具（尤其是 Agent）可把
``ToolProgressEvent`` / 结构化 ``xy`` 帧推进主会话 SSE，而无需改
``execute()`` 签名。asyncio 并发下每个 Task 有独立 ContextVar 副本。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Callable

ProgressSink = Callable[[Any], None]

_sink: ContextVar[ProgressSink | None] = ContextVar(
	"xeyo_tool_progress_sink", default=None
)


def set_progress_sink(fn: ProgressSink | None) -> Token:
	return _sink.set(fn)


def reset_progress_sink(token: Token) -> None:
	_sink.reset(token)


def emit_progress(event: Any) -> None:
	fn = _sink.get()
	if not callable(fn):
		return
	try:
		fn(event)
	except Exception:  # noqa: BLE001
		pass


__all__ = [
	"ProgressSink",
	"emit_progress",
	"reset_progress_sink",
	"set_progress_sink",
]
