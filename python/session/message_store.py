from __future__ import annotations

from msgtypes.message import Message


class MessageStore:
	def __init__(self, initial: list[Message] | None = None) -> None:
		self._items: list[Message] = list(initial or [])
		self._api_cache: list[dict] | None = None

	def append(self, msg: Message) -> None:
		self._items.append(msg)
		self._api_cache = None

	def insert(self, index: int, msg: Message) -> None:
		"""在指定位置插入（修复未配对 tool call 用）；同样使 api 缓存失效。"""
		self._items.insert(index, msg)
		self._api_cache = None

	def replace(self, items: list[Message]) -> None:
		"""整表替换（回溯 resync 用：内存历史对齐重写后的 transcript 前缀）。"""
		self._items = list(items)
		self._api_cache = None

	def __len__(self) -> int:
		return len(self._items)

	@property
	def items(self) -> list[Message]:
		return self._items

	def as_api_messages(self) -> list[dict]:
		"""转成给模型看的 dict 列表（不含单独 system；system 由 PromptAssembler 加）。

		OpenAI/DeepSeek 要求 assistant.tool_calls 后必须跟 role=tool + tool_call_id。
		结果按消息追加/插入缓存，避免每轮重建整个 dict 列表。
		"""
		if self._api_cache is not None:
			return self._api_cache
		out: list[dict] = []
		for m in self._items:
			if m.role == "tool":
				row: dict = {
					"role": "tool",
					"content": m.content,
				}
				if m.tool_call_id:
					row["tool_call_id"] = m.tool_call_id
				if m.name:
					row["name"] = m.name
				out.append(row)
			else:
				out.append({"role": m.role, "content": m.content})
		self._api_cache = out
		return out