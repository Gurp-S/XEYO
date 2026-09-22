"""provider 统一 ModelEvent 边界契约。"""

from __future__ import annotations

import pytest

from engine.model_events import ModelProtocolError, normalize_model_event
from model.chunks import ModelChunk
from msgtypes.message import ToolUse


def test_model_event_accepts_normalized_text_and_tool() -> None:
	assert normalize_model_event(ModelChunk(kind="text_delta", text="x")).text == "x"
	event = normalize_model_event(
		ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(id="c1", name="Read", input={"path": "a"}),
		)
	)
	assert event.tool_use is not None
	assert event.tool_use.name == "Read"


@pytest.mark.parametrize(
	"event",
	[
		object(),
		ModelChunk(kind="tool_use"),
		ModelChunk(kind="text_delta", text=1),  # type: ignore[arg-type]
		ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(id="", name="Read", input={}),
		),
	],
)
def test_model_event_rejects_malformed_provider_output(event) -> None:  # type: ignore[no-untyped-def]
	with pytest.raises(ModelProtocolError):
		normalize_model_event(event)
