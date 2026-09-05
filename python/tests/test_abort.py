import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
from typing import AsyncIterator

import pytest

from engine.abort import AbortController
from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from msgtypes.events import FinalEvent, StoppedEvent


class SlowModel:
	"""慢速逐字输出，便于中途 interrupt。"""

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		text = "abcdefghijklmnopqrstuvwxyz"
		for ch in text:
			abort.raise_if_aborted()
			yield ModelChunk(kind="text_delta", text=ch)
			await asyncio.sleep(0.01)


def _make_engine(model: object, reg: ToolRegistry, max_turns: int = 4) -> QueryEngine:
	return QueryEngine(
		{
			"cwd": ".",
			"tools": reg,
			"model_client": model,  # type: ignore[typeddict-item]
			"max_turns": max_turns,
		}
	)


@pytest.mark.asyncio
async def test_abort_mid_stream():
	reg = ToolRegistry()
	reg.register(EchoTool())
	eng = _make_engine(SlowModel(), reg, max_turns=4)

	async def killer():
		await asyncio.sleep(0.03)
		eng.interrupt()

	task = asyncio.create_task(killer())
	events = []
	async for ev in eng.submit("hello"):
		events.append(ev)
	await task

	assert any(
		isinstance(e, StoppedEvent) and e.reason == "aborted" for e in events
	)

	# 下一轮 reset 后仍可成功
	events2 = []
	async for ev in eng.submit("hello"):
		events2.append(ev)
		if isinstance(ev, StoppedEvent) and ev.reason == "aborted":
			# 若 killer 残留不应影响；本轮未再 interrupt
			pass
	assert any(isinstance(e, FinalEvent) for e in events2)


if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))
