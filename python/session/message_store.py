from __future__ import annotations

from msgtypes.message import Message


class MessageStore:
	def __init__(self, initial: list[Message] | None = None) -> None:
		self._items: list[Message] = list(initial or [])
		self._api_cache: list[dict] | None = None
		#: 投影是否包含 T_now 留痕条目（hidden system note）。默认包含；
		#: 声道解析为 env/skip（厂商拒绝中段 system）时由引擎置 False——
		#: 留痕只在 system 声道下才允许出现在模型输入里。
		self._notes_visible: bool = True

	def set_note_policy(self, include: bool) -> None:
		"""设置投影是否包含留痕条目（变更即失效投影缓存）。"""
		flag = bool(include)
		if flag == self._notes_visible:
			return
		self._notes_visible = flag
		self._api_cache = None

	def note_fingerprints(self, *, start: int = 0) -> set[tuple[str, str]]:
		"""管道 2 去重的**真相源**：``start`` 之后仍在可见面的留痕身份。

		C0/C1 只改 tool_result 内容、不丢消息；C2 用一个摘要替换左段
		``[0, compact_cursor)`` ⇒ 左段里的留痕不再可见，故调用方传压缩游标。
		``start`` 使用模型投影的消息下标，而不是内部 append-only 历史下标；
		旧版本留痕在模型面折叠后不会造成下标漂移。
		留痕被 A 闸排除（``_notes_visible=False``）时返回空集。
		"""
		if not self._notes_visible:
			return set()
		out: set[tuple[str, str]] = set()
		items = self._items
		projection_index = 0
		start_index = max(0, int(start or 0))
		latest: dict[str, int] = {}
		for index, item in enumerate(items):
			key = getattr(item, "note_key", "")
			if key:
				latest[key] = index
		for index, item in enumerate(items):
			key = getattr(item, "note_key", "")
			if key and latest.get(key) != index:
				continue
			if key and projection_index >= start_index:
				out.add((key, getattr(item, "note_fp", "") or ""))
			projection_index += 1
		return out

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
		# T_now 留痕在历史面 append-only；模型投影是按 note_key 的最新值，
		# 否则同一状态每次变化都会把旧版本继续带进上下文。
		latest_note_index: dict[str, int] = {}
		for index, item in enumerate(self._items):
			key = getattr(item, "note_key", "")
			if key:
				latest_note_index[key] = index
		for index, m in enumerate(self._items):
			note_key = getattr(m, "note_key", "")
			if note_key and (
				not self._notes_visible or latest_note_index.get(note_key) != index
			):
				# 历史保留所有版本供审计/恢复；模型只看到每个状态键的最新版本。
				continue
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
