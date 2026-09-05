"""内存 todo 存储。

按 key 隔离：主会话 ``default``，子 agent 可用 ``agent-{id}``。
进程内热路径；落盘由 memory.working sidecar + transcript 恢复兜底。
"""

from __future__ import annotations

from tools.todo_write_tool.types import TodoItem

DEFAULT_TODO_KEY = "default"


class TodoStore:
	"""会话级清单。按 key 存储，支持 agentId 隔离。"""

	def __init__(self) -> None:
		self._by_key: dict[str, list[TodoItem]] = {}

	def get(self, key: str = DEFAULT_TODO_KEY) -> list[TodoItem]:
		return list(self._by_key.get(key, []))

	def set(self, todos: list[TodoItem], *, key: str = DEFAULT_TODO_KEY) -> None:
		self._by_key[key] = list(todos)

	def clear(self, key: str = DEFAULT_TODO_KEY) -> None:
		self._by_key.pop(key, None)

	def keys(self) -> list[str]:
		return list(self._by_key.keys())
