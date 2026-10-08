"""会话级 readFileState — Read 写入，Write/Edit 校验先读与新鲜度。"""

from __future__ import annotations

import os
import threading
import time
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
	#: 本会话见过的该路径正文哈希（与 engine.write_store 同口径）。
	#: sidecar 恢复时正文不入 json，但**哈希必须留下**（2026-09-20）：否则重启后
	#: 没有可比对的基线，写入要么被 missing_read 拒绝，要么退化成"拿盘上内容当
	#: 基线"（等于不校验）。有了它，重启后仍能判定"盘上内容是否还是我读过的那版"。
	content_hash: str = ""
	view_digest: str = ""
	view_visible: bool = True
	#: 这条基线的来源：``read`` = Read 工具；``bash`` = Bash 的整文件读（弱基线）。
	#: 弱基线不携带正文（正文只在 Bash 结果里），能否当基线由
	#: :func:`bash_baseline_hash` 的开关 + 全文 + mtime 三条件决定。
	via: str = "read"


def _content_hash_text(content: str) -> str:
	"""与 ``engine.write_store._content_hash_text`` 同口径的哈希（lazy import）。

	tools 层不在模块级反向依赖 engine；导入失败退化为同口径本地实现，保证
	base_hashes 比较不会因两处实现漂移而误报。
	"""
	try:
		from engine.write_store import _content_hash_text as _h

		return _h(content)
	except Exception:  # noqa: BLE001 — 导入失败不阻断读登记
		import hashlib

		return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _max_entries_from_env(default: int = 128) -> int:
	raw = os.environ.get("XEYO_READ_STATE_MAX_ENTRIES", "").strip()
	if not raw:
		return default
	try:
		return max(8, int(raw))
	except ValueError:
		return default


#: 基线世代：本册每淘汰/清空一次 +1。写给"没有基线"的报错用——把**从没读过**
#: 与**读过但基线已被淘汰**分开，模型才知道该重读同段还是从头读
#: （本场实测被同一句 reason 拦了两次，只能靠试）。
_EPOCH = 0
_DROPPED_MAX = 512
_LEDGER_LOCK = threading.Lock()
_DROPPED_KEYS: list[str] = []


def _note_dropped(keys: list[str]) -> None:
	global _EPOCH
	with _LEDGER_LOCK:
		_EPOCH += 1
		_DROPPED_KEYS.extend(keys)
		while len(_DROPPED_KEYS) > _DROPPED_MAX:
			_DROPPED_KEYS.pop(0)


def baseline_epoch() -> int:
	"""当前基线世代（每次淘汰/清空 +1）。"""
	return _EPOCH


def baseline_dropped(path: str) -> bool:
	"""这条路径**读过**、但其基线已不在册（淘汰/清空）→ True；从没读过 → False。"""
	key = ReadFileState._key(path)
	with _LEDGER_LOCK:
		return key in _DROPPED_KEYS


#: Bash 读证据：``path → {mtime_ms, whole_file, lines, ts}``。
#: 只有"整文件 + 输出未被截断"的读才是证据：``cat big.py | head -40`` 只看了前 40 行，
#: 拿它当基线等于放行盲改。上限只为防长会话无界（值只有几十字节）。
_BASH_READS: dict[str, dict] = {}
_BASH_READS_MAX = 256


def record_bash_read(
	path: str, *, mtime_ms: int, whole_file: bool, lines: int | None = None
) -> None:
	"""登记一次 Bash 读（由 Bash 工具在结果落地后调用）。"""
	key = ReadFileState._key(path)
	if not key:
		return
	with _LEDGER_LOCK:
		_BASH_READS[key] = {
			"mtime_ms": int(mtime_ms or 0),
			"whole_file": bool(whole_file),
			"lines": int(lines or 0),
			"ts": time.time(),
		}
		while len(_BASH_READS) > _BASH_READS_MAX:
			_BASH_READS.pop(next(iter(_BASH_READS)), None)


def bash_read_evidence(path: str) -> dict | None:
	"""该路径的 Bash 读证据（没有 → None）。报错归因与弱基线都读它。"""
	key = ReadFileState._key(path)
	with _LEDGER_LOCK:
		row = _BASH_READS.get(key)
		return dict(row) if row else None


def _bash_baseline_enabled() -> bool:
	raw = os.environ.get("XEYO_READ_BASELINE_BASH_EVIDENCE", "").strip().lower()
	return raw in {"1", "true", "yes", "on"}


def bash_baseline_hash(path: str, *, enabled: bool | None = None) -> str:
	"""Bash 的整文件读能否当写基线：能则返回当前磁盘正文哈希，否则空串。

	三条同时成立才放行（缺一即维持原 ``missing_read`` 拒绝）：
	  1. 开关 ``XEYO_READ_BASELINE_BASH_EVIDENCE`` 开（默认关 = 旁路形态）；
	  2. 有该路径证据，且那次读**看到了全文**（输出未被工具截断）；
	  3. 磁盘 mtime 与那次读一致 ⇒ 之后没人改过。
	放行后仍由 Edit 的 ``old_string`` 匹配兜底，弱基线不改变"必须与所见内容一致"这层。
	"""
	if enabled is None:
		enabled = _bash_baseline_enabled()
	if not enabled:
		return ""
	evidence = bash_read_evidence(path)
	if not evidence or not evidence.get("whole_file"):
		return ""
	try:
		stat = os.stat(path)
	except OSError:
		return ""
	if int(stat.st_mtime * 1000) != int(evidence.get("mtime_ms") or 0):
		return ""
	try:
		with open(path, "rb") as fh:
			raw = fh.read()
	except OSError:
		return ""
	return _content_hash_text(raw.decode("utf-8", "replace"))


def missing_read_detail(path: str) -> str:
	"""``missing_read`` 的三种事实（两把写工具的报错共用一处，免得漂移）。

	事故形态（本场实测被同一句 reason 拦了两次）：模型只拿到"没读过"，无法判断该
	重读同一段、从头读、还是先 Read 一次——只能试。三种形态：
	  - ``never read in this session``：真没读过；
	  - ``baseline dropped at epoch N``：读过但基线被淘汰/清空；
	  - ``bash read on record (…)``：只在 Bash 里读过（附"是否全文 + 行数"）。
	只陈述结果，不写"应该怎么做"。
	"""
	evidence = bash_read_evidence(path)
	if baseline_dropped(path):
		return f"baseline dropped at epoch {baseline_epoch()}"
	if evidence:
		scope = "full file" if evidence.get("whole_file") else "truncated output"
		lines = int(evidence.get("lines") or 0)
		seen = f", {lines} lines" if lines else ""
		return f"bash read on record ({scope}{seen}); no Read baseline"
	return "never read in this session"


class ReadFileState:
	"""按绝对路径缓存已读文件快照（同一 registry / session 共享）。

	条目含文件全文（供 Edit 校验先读），必须限幅：超出 max_entries 时
	按 LRU 淘汰最久未访问的路径，防止长会话内存无界增长。
	"""

	def __init__(
		self, *, max_entries: int | None = None, conversation_id: str = ""
	) -> None:
		self._entries: dict[str, FileStateEntry] = {}
		# 并发保护（2026-09-20）：同一批 tool_use 会并发执行（Read/Glob/Grep/
		# Bash 路由都可能登记），而本册是进程级共享；无锁时遍历
		# （snapshot_meta）与写入并发 ⇒ RuntimeError: dictionary changed size
		# during iteration，整次工具调用 fail-closed 丢结果。
		self._lock = threading.RLock()
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
				content_hash=_content_hash_text(content),
			),
		)


	@staticmethod
	def _key(path: str) -> str:
		# Windows 大小写/分隔符不敏感：Read "D:\Foo.py" 与 Edit "d:/foo.py"
		# 必须命中同一条目，否则报 "has not been read yet" 误报。
		return os.path.normcase(os.path.normpath(path))

	def get(self, path: str) -> FileStateEntry | None:
		key = self._key(path)
		with self._lock:
			entry = self._entries.get(key)
			if entry is not None:
				self._entries.pop(key, None)
				self._entries[key] = entry  # 触碰即刷新新鲜度
			return entry

	def set(self, path: str, entry: FileStateEntry) -> None:
		key = self._key(path)
		with self._lock:
			self._entries.pop(key, None)
			self._entries[key] = entry
			while len(self._entries) > self._max_entries:
				evicted = next(iter(self._entries))
				_note_dropped([evicted])
				self._entries.pop(evicted)

	def clear(self) -> None:
		with self._lock:
			if self._entries:
				_note_dropped(list(self._entries))
			self._entries.clear()

	def sync_visible_views(self, digests: set[str]) -> None:
		"""只更新 Read 去重资格，保留 Edit/Write 的正文、时间戳和哈希。"""
		with self._lock:
			for entry in self._entries.values():
				entry.view_visible = bool(entry.view_digest and entry.view_digest in digests)

	def snapshot_meta(self) -> dict[str, dict]:
		"""序列化 mtime/offset，不含文件正文（给 WorkingSnapshot sidecar）。"""
		out: dict[str, dict] = {}
		with self._lock:
			rows = list(self._entries.items())
		for path, entry in rows:
			out[path] = {
				"timestamp": entry.timestamp,
				"offset": entry.offset,
				"limit": entry.limit,
				"is_partial_view": entry.is_partial_view,
				"content_hash": entry.content_hash,
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
					content_hash=str(row.get("content_hash") or ""),
				),
			)

	def __contains__(self, path: object) -> bool:
		return isinstance(path, str) and self._key(path) in self._entries
