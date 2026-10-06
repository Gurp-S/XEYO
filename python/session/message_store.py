from __future__ import annotations

from msgtypes.message import Message
from session.state_projection import current_context_items
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
		self._api_items: list[Message] = []

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

	def note_fingerprints(self, *, start: int = 0, projected: list[dict] | None = None) -> set[tuple[str, str]]:
		"""管道 2 去重的真相源：实际投影中仍完整存在的状态身份。

		生产传实际 ``projected``：WSC 吸收右界可能超过 compact_cursor，不能
		拿游标猜可见性。``start`` 仅保留非压缩调用方的 API 下标兼容口径，
		实际投影必须包含相同身份、角色和完整正文，才允许跳过状态重发。
		被 A 闸排除的留痕（system 形态 + 闸门关闭）不计入可见面。
		"""
		rows = self._api_cache if self._api_cache is not None else self.as_api_messages()
		visible_rows = projected if projected is not None else rows[max(0, int(start or 0)):]
		if projected is not None:
			actual = {(row["note_key"], row.get("note_fp") or ""): row
			          for row in projected if row.get("note_key")}
			visible_rows = []
			for item in self._api_items:
				row = actual.get((item.note_key, item.note_fp)) if item.note_key else None
				if row is not None and row.get("role") == item.role and row.get("content") == item.content:
					visible_rows.append(row)
		return {
			(row["note_key"], row.get("note_fp") or "")
			for row in visible_rows
			if row.get("note_key")
		}

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
		ordered = reorder_system_messages_around_tool_results(self._items)
		ordered = discard_unpaired_tool_results(ordered)
		if ordered is not self._items:
			self._items = ordered
			self._api_cache = None
		out: list[dict] = []
		# API 输入和可见性台账共享这份状态选择，禁止独立扫描出另一套下标。
		selected = current_context_items(self._items, include_system_notes=self._notes_visible)
		self._api_items = selected
		for m in selected:
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
				row = {"role": m.role, "content": m.content}
				if m.note_key:
					row.update(note_key=m.note_key, note_fp=m.note_fp)
				out.append(row)
		self._api_cache = out
		return out
