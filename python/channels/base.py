"""Channel 抽象 — 微信（及后续渠道）在此接入。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
	"""来自任意 channel 的标准化入站消息。"""

	text: str
	session_id: str
	sender_id: str = ""
	raw: dict[str, Any] | None = None
	images: tuple[str, ...] = ()


class Channel(ABC):
	"""入站 → 入队 agent 回合；出站 → 仅投递最终文本。"""

	name: str = "channel"

	@abstractmethod
	async def handle_inbound(self, message: InboundMessage) -> str:
		"""接收用户消息；返回 job_id（或 channel 确认 id）。"""

	@abstractmethod
	async def send_final(self, *, session_id: str, text: str, meta: dict[str, Any] | None = None) -> None:
		"""在该 channel 上向用户投递 agent 最终结果。"""
