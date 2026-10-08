"""Stable UI/transcript identity for one logical model output, including retries."""
from dataclasses import dataclass, field
from uuid import uuid4

from msgtypes.events import AssistantDelta
from msgtypes.message import assistant_text_message


@dataclass(frozen=True)
class AssistantOutput:
    message_id: str = field(default_factory=lambda: uuid4().hex)

    def delta(self, text: str) -> AssistantDelta:
        return AssistantDelta(text=text, message_id=self.message_id)

    def message(self, text, tool_uses=None, **kwargs):
        return assistant_text_message(text, tool_uses, message_id=self.message_id, **kwargs)
