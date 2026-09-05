from __future__ import annotations

from typing import AsyncIterator, Protocol

from engine.abort import AbortController
from model.chunks import ModelChunk


class ModelClient(Protocol):
	def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]: ...
