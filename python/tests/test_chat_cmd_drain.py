"""_drain_after_interrupt：超时不得把 CancelledError 注入引擎事件流。

旧 bug：``asyncio.wait_for(_drain(), ...)`` 超时 cancel 在途
``aiter.__anext__()`` → CancelledError 注入引擎流生成器并拆毁它
（与 server SSE 订阅 wait_for(__anext__) 同款 bug）。
修复后：shield 保住在途 resumption，流在后台自然收尾，可正常 aclose。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.chat_cmd as chat_cmd
from msgtypes.events import StoppedEvent


class _Renderer:
	def __init__(self) -> None:
		self.events: list[object] = []
		self.json_mode = True  # 跳过 console 输出

	def emit(self, ev: object) -> None:
		self.events.append(ev)


@pytest.mark.asyncio
async def test_drain_timeout_does_not_destroy_engine_aiter(monkeypatch):
	destroyed = False
	stall_done = asyncio.Event()

	async def fake_stream():
		nonlocal destroyed
		yield SimpleNamespace(kind="delta")  # 超时前正常消费并 emit
		try:
			await asyncio.sleep(0.2)  # 引擎卡住 > drain 超时（0.05s）
		except asyncio.CancelledError:
			destroyed = True  # 被注入 CancelledError = 被拆毁
			raise
		stall_done.set()
		yield StoppedEvent(reason="aborted")

	monkeypatch.setattr(chat_cmd, "_DRAIN_TIMEOUT_SEC", 0.05)
	agen = fake_stream()
	renderer = _Renderer()

	await asyncio.wait_for(
		chat_cmd._drain_after_interrupt(agen, renderer=renderer), timeout=2.0
	)

	assert [e.kind for e in renderer.events] == ["delta"]
	assert not destroyed, "超时把 CancelledError 注入引擎流并拆毁了生成器"
	# 等后台 shield 的在途 __anext__ 自然完成，再验证生成器仍可干净收尾。
	await asyncio.wait_for(stall_done.wait(), timeout=2.0)
	await agen.aclose()


@pytest.mark.asyncio
async def test_drain_stops_at_stopped_event(monkeypatch):
	"""引擎正常发出 StoppedEvent：drain 立即结束并消费到终止事件。"""
	monkeypatch.setattr(chat_cmd, "_DRAIN_TIMEOUT_SEC", 1.0)

	async def fake_stream():
		yield SimpleNamespace(kind="delta")
		yield StoppedEvent(reason="aborted")

	renderer = _Renderer()
	await asyncio.wait_for(
		chat_cmd._drain_after_interrupt(fake_stream(), renderer=renderer),
		timeout=2.0,
	)
	assert len(renderer.events) == 2
	assert isinstance(renderer.events[1], StoppedEvent)
