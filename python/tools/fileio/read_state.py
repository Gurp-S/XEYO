"""会话级 readFileState — Read 写入，Write/Edit 校验先读与新鲜度。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class FileStateEntry:
	content: str
	timestamp: int  # mtime_ms 向下取整
	offset: Optional[int] = None
	limit: Optional[int] = None
	is_partial_view: bool = False
	#: 正文是否与 timestamp 同源（Read/Edit/Write 后为 True）。WorkingSnapshot
	#: sidecar 恢复的条目只存 mtime 不存正文（content 为空占位），此时
	#: "mtime 变了 + 内容对不上" 不能证明文件被外人改过——Edit 应放行，
	#: 由 old_string 匹配兜底，而不是必然误报 modified-since-read。
	content_known: bool = True
	#: 最近一次写入该路径的会话树根（见 session_tree_root）；空 = 未登记写入者。
	#: 供跨会话"外部修改"归因：与当前会话树根不同 -> external。
	writer_session_id: str = ""
	#: 写入时刻的 unix 秒（供归因展示"于 HH:MM"）。
	writer_ts: float = 0.0


def _max_entries_from_env(default: int = 128) -> int:
	raw = os.environ.get("XEYO_READ_STATE_MAX_ENTRIES", "").strip()
	if not raw:
		return default
	try:
		return max(8, int(raw))
	except ValueError:
		return default


class ReadFileState:
	"""按绝对路径缓存已读文件快照（同一 registry / session 共享）。

	条目含文件全文（供 Edit 校验先读），必须限幅：超出 max_entries 时
	按 LRU 淘汰最久未访问的路径，防止长会话内存无界增长。
	"""

	def __init__(
		self, *, max_entries: int | None = None, conversation_id: str = ""
	) -> None:
		self._entries: dict[str, FileStateEntry] = {}
		self._max_entries = max(8, int(max_entries or _max_entries_from_env()))
		#: 本册所属会话树根（主会话 id，或子 agent 会话去掉 __agent__ 后缀）。
		#: 用于把"被另一聊天会话写入"与"本会话树内部写入"区分开。
		self._conversation_id = (conversation_id or "").strip()

	@property
	def conversation_id(self) -> str:
		return self._conversation_id

	def set_conversation_id(self, conversation_id: str | None) -> None:
		self._conversation_id = (conversation_id or "").strip()

	def set_written(
		self,
		path: str,
		content: str,
		timestamp: int,
		session_id: str,
		*,
		offset: Optional[int] = None,
		limit: Optional[int] = None,
	) -> None:
		"""Write/Edit 落盘后登记：条目携带写入者会话（供跨会话外部归因）。"""
		import time as _time

		self.set(
			path,
			FileStateEntry(
				content=content,
				timestamp=timestamp,
				offset=offset,
				limit=limit,
				content_known=True,
				writer_session_id=(session_id or "").strip(),
				writer_ts=_time.time(),
			),
		)


	@staticmethod
	def _key(path: str) -> str:
		# Windows 大小写/分隔符不敏感：Read "D:\Foo.py" 与 Edit "d:/foo.py"
		# 必须命中同一条目，否则报 "has not been read yet" 误报。
		return os.path.normcase(os.path.normpath(path))

	def get(self, path: str) -> FileStateEntry | None:
		key = self._key(path)
		entry = self._entries.get(key)
		if entry is not None:
			self._entries.pop(key, None)
			self._entries[key] = entry  # 触碰即刷新新鲜度
		return entry

	def set(self, path: str, entry: FileStateEntry) -> None:
		key = self._key(path)
		self._entries.pop(key, None)
		self._entries[key] = entry
		while len(self._entries) > self._max_entries:
			self._entries.pop(next(iter(self._entries)))

	def clear(self) -> None:
		self._entries.clear()

	def snapshot_meta(self) -> dict[str, dict]:
		"""序列化 mtime/offset，不含文件正文（给 WorkingSnapshot sidecar）。"""
		out: dict[str, dict] = {}
		for path, entry in self._entries.items():
			out[path] = {
				"timestamp": entry.timestamp,
				"offset": entry.offset,
				"limit": entry.limit,
				"is_partial_view": entry.is_partial_view,
			}
		return out

	def load_meta(self, meta: dict[str, dict]) -> None:
		"""从 sidecar 恢复元数据；正文留空且 content_known=False，避免把整份
		文件写入 json。正文未知时 Edit/Write 不得用"内容对不上"判改造。"""
		for path, row in (meta or {}).items():
			if not isinstance(row, dict):
				continue
			existing = self.get(path)
			self.set(
				path,
				FileStateEntry(
					content=existing.content if existing else "",
					timestamp=int(row.get("timestamp") or 0),
					offset=row.get("offset"),
					limit=row.get("limit"),
					is_partial_view=bool(row.get("is_partial_view")),
					content_known=bool(existing and existing.content),
				),
			)

	def __contains__(self, path: object) -> bool:
		return isinstance(path, str) and self._key(path) in self._entries
