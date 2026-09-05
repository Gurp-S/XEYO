import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from model.fake import FakeModelClient
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from msgtypes.events import FinalEvent
from msgtypes.message import user_message


@pytest.mark.asyncio
async def test_plain():
	store = MessageStore([user_message("hello")])
	reg = ToolRegistry()
	reg.register(EchoTool())
	events = []
	async for ev in query_loop(
		store=store,
		model=FakeModelClient(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		events.append(ev)
	assert any(isinstance(e, FinalEvent) for e in events)
	assert store.items[-1].role == "assistant"


if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))