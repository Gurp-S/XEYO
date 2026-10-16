import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from engine.query_engine import build_default_engine
from msgtypes.events import FinalEvent, StoppedEvent, ToolCallEvent


@pytest.mark.asyncio
async def test_submit_plain():
	eng = build_default_engine(model_backend="fake")
	finals = []
	async for ev in eng.submit("hello"):
		if isinstance(ev, FinalEvent):
			finals.append(ev)
	assert finals and finals[0].text.startswith("ok:")


@pytest.mark.asyncio
async def test_submit_echo():
	eng = build_default_engine(model_backend="fake")
	call_id = None
	final = None
	async for ev in eng.submit("echo:hi"):
		if isinstance(ev, ToolCallEvent):
			call_id = ev.tool_use_id
		if isinstance(ev, FinalEvent):
			final = ev
	assert call_id and final
	# The fake model echoes the complete model-visible result and its receipt.
	prefix, body = final.text.split("\n", 1)
	assert prefix.startswith("echoed: 执行回执身份=") and body == "hi"
	assert json.loads(prefix.removeprefix("echoed: 执行回执身份=")) == {"call_id": call_id}


@pytest.mark.asyncio
async def test_interrupt_then_submit():
	eng = build_default_engine(model_backend="fake")
	eng.interrupt()
	# submit 开头会 reset，应仍可完成
	events = []
	async for ev in eng.submit("hello"):
		events.append(ev)
	assert any(isinstance(e, FinalEvent) for e in events)
	assert not any(
		isinstance(e, StoppedEvent) and e.reason == "aborted" for e in events
	)


if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))
