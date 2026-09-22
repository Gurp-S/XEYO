from __future__ import annotations

from msgtypes.message import Message
from session.tool_sequence import (
	discard_unpaired_tool_results,
	reorder_system_messages_around_tool_results,
)


class MessageStore:
	def __init__(self, initial: list[Message] | None = None) -> None:
		self._items: list[Message] = list(initial or [])
		self._api_cache: list[dict] | None = None
		#: 投影是否包含 T_now 留痕条目（hidden system note）。默认包含；
		#: 声道解析为 env/skip（厂商拒绝中段 system）时由引擎置 False——
		#: 留痕只在 system 声道下才允许出现在模型输入里。
		self._notes_visible: bool = True

	def set_note_policy(self, include: bool) -> None:
		"""设置投影是否携带 **system 形态**留痕（变更即失效投影缓存）。

		口径（对齐 Codex：上下文片段是独立 item，不是厂商特例）：A 闸只约束
		role=system 的留痕——不吃中段 system 的厂商必须逐出它。user 形态的通报
		片段是普通 user 消息，任何厂商都收，因此**不受本闸影响**。否则一次
		system→片段的降档会把降级前已落库的 system 留痕又送回请求里，逐枪 4xx。
		"""
		flag = bool(include)
		if flag == self._notes_visible:
			return
		self._notes_visible = flag
		self._api_cache = None

	def _note_hidden(self, item: Message) -> bool:
		"""该条留痕是否应被逐出模型投影（身份由 note_key 决定，与形态无关）。

		两种逐出理由：A 闸关闭时的 system 形态（厂商不吃中段 system）；已撤回的
		维度（状态不再存在 ⇒ 那一版不能再冒充当前事实）。
		"""
		key = getattr(item, "note_key", "")
		if not key:
			return False
		if getattr(item, "note_retracted", False):
			return True
		return not self._notes_visible and item.role == "system"

	def retract_note(self, key: str) -> int:
		"""把某维度的留痕逐出模型投影（就地标记；历史行不删、正文不改）。

		返回被标记的条数。撤回只影响模型所见：审计面与用户面照常能取出那一版
		（``include_notes=1``），因为它是发生过的事实。
		"""
		k = (key or "").strip()
		if not k:
			return 0
		n = 0
		for item in self._items:
			if (
				getattr(item, "note_key", "") == k
				and not getattr(item, "note_retracted", False)
			):
				item.note_retracted = True
				n += 1
		if n:
			self._api_cache = None
		return n

	def note_fingerprints(self, *, start: int = 0) -> set[tuple[str, str]]:
		"""管道 2 去重的**真相源**：``start`` 之后仍在可见面的留痕身份。

		C0/C1 只改 tool_result 内容、不丢消息；C2 用一个摘要替换左段
		``[0, compact_cursor)`` ⇒ 左段里的留痕不再可见，故调用方传压缩游标。
		``start`` 使用模型投影的消息下标，而不是内部 append-only 历史下标；
		旧版本留痕在模型面折叠后不会造成下标漂移。
		被 A 闸排除的留痕（system 形态 + 闸门关闭）不计入可见面。
		"""
		out: set[tuple[str, str]] = set()
		items = self._items
		projection_index = 0
		start_index = max(0, int(start or 0))
		latest: dict[str, int] = {}
		for index, item in enumerate(items):
			key = getattr(item, "note_key", "")
			if key and not self._note_hidden(item):
				latest[key] = index
		for index, item in enumerate(items):
			key = getattr(item, "note_key", "")
			if key and (self._note_hidden(item) or latest.get(key) != index):
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
		ordered = reorder_system_messages_around_tool_results(self._items)
		ordered = discard_unpaired_tool_results(ordered)
		if ordered is not self._items:
			self._items = ordered
			self._api_cache = None
		if self._api_cache is not None:
			return self._api_cache
		out: list[dict] = []
		# T_now 留痕在历史面 append-only；模型投影是按 note_key 的最新值，
		# 否则同一状态每次变化都会把旧版本继续带进上下文。
		latest_note_index: dict[str, int] = {}
		for index, item in enumerate(self._items):
			key = getattr(item, "note_key", "")
			if key and not self._note_hidden(item):
				latest_note_index[key] = index
		for index, m in enumerate(self._items):
			note_key = getattr(m, "note_key", "")
			if note_key and (
				self._note_hidden(m) or latest_note_index.get(note_key) != index
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
