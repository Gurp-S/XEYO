"""同工作区多会话在场表：登记 busy / 最近写入 / todo / git，供 T_now 提醒与 peer ASK。

可见性只走提醒制（T_now + 人类侧栏），不把其他会话 transcript 暴露给模型工具。

后端分派（coord 阶段 0，2026-09-09）：
- ``memory``（默认）= :class:`SessionPresenceRegistry`，进程内 dict，行为与
  coord 引入前一致；
- ``file`` = :class:`coord.presence_adapter.FileBackedPresence`，同一
  :class:`PresenceState` 逻辑经 CoordFileStore 持久化到 ``<ws>/.xeyo/coord/``，
  跨进程可见。判定按 cwd（workspace 级配置生效），判定结果按 root 缓存。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


FILE_OWNERSHIP_TTL_SEC = 10 * 60
QUEUED_NOTICE_TTL_SEC = 30 * 60
MAX_OWNED_PATHS = 64
MAX_TODO_BRIEF = 2
MAX_QUEUED_NOTICES = 8

PEER_CHOICES = ("deny", "remind", "allow")


def _norm_root(cwd: str | Path) -> str:
	return os.path.realpath(os.path.abspath(os.path.expanduser(str(cwd or "").strip() or ".")))


def _rel_path(root: str, path: str) -> str:
	raw = (path or "").strip().replace("\\", "/")
	if not raw:
		return ""
	try:
		abs_p = Path(path).expanduser()
		if not abs_p.is_absolute():
			abs_p = Path(root) / path
		rel = abs_p.resolve().relative_to(Path(root))
		return rel.as_posix()
	except (OSError, ValueError):
		return raw.lstrip("./")


def _short_id(session_id: str) -> str:
	sid = (session_id or "").strip()
	if len(sid) <= 10:
		return sid
	return sid[-8:]


# 子 agent 会话键形如 "{main}__agent__{agent_id}"（见 memory.agent_scope.scoped_session_id）。
# 会话树根 = __agent__ 之前的主会话 id。主会话与它的子 agent 共享同一树根，
# 因此"同一会话树内部写入"不算外部修改。
_SCOPED_TOKEN = "__agent__"


def session_tree_root(session_id: str) -> str:
	"""返回会话所属会话树根：主会话 id；子 agent 会话去掉 __agent__ 后缀。"""
	sid = (session_id or "").strip()
	if not sid:
		return ""
	if _SCOPED_TOKEN in sid:
		return sid.split(_SCOPED_TOKEN, 1)[0].strip("_")
	return sid


@dataclass
class SessionPresenceEntry:
	session_id: str
	cwd: str
	title: str = ""
	busy: bool = False
	#: relative path -> last write unix ts
	owned_files: dict[str, float] = field(default_factory=dict)
	todo_brief: list[str] = field(default_factory=list)
	current_tool: str = ""
	git_op: str = ""
	updated_at: float = 0.0
	#: queued T_now notices for this session (from peers choosing continue/remind)
	queued_notices: list[tuple[float, str]] = field(default_factory=list)

	def prune_owned(self, *, now: float | None = None, ttl: float = FILE_OWNERSHIP_TTL_SEC) -> None:
		ts = now if now is not None else time.time()
		self.owned_files = {
			p: t for p, t in self.owned_files.items() if (ts - t) <= ttl
		}

	def prune_notices(self, *, now: float | None = None) -> None:
		ts = now if now is not None else time.time()
		self.queued_notices = [
			(t, text)
			for t, text in self.queued_notices
			if (ts - t) <= QUEUED_NOTICE_TTL_SEC
		][-MAX_QUEUED_NOTICES:]

	def to_dict(self) -> dict[str, Any]:
		return {
			"session_id": self.session_id,
			"cwd": self.cwd,
			"title": self.title,
			"busy": self.busy,
			"owned_files": dict(self.owned_files),
			"todo_brief": list(self.todo_brief),
			"current_tool": self.current_tool,
			"git_op": self.git_op,
			"updated_at": float(self.updated_at),
			"queued_notices": [[t, text] for t, text in self.queued_notices],
		}

	@classmethod
	def from_dict(cls, raw: dict[str, Any]) -> "SessionPresenceEntry":
		queues = [
			(float(pair[0]), str(pair[1]))
			for pair in (raw.get("queued_notices") or [])
			if isinstance(pair, (list, tuple)) and len(pair) >= 2
		]
		owned = raw.get("owned_files")
		return cls(
			session_id=str(raw.get("session_id") or ""),
			cwd=str(raw.get("cwd") or ""),
			title=str(raw.get("title") or ""),
			busy=bool(raw.get("busy") or False),
			owned_files={
				str(k): float(v) for k, v in (owned or {}).items()
			} if isinstance(owned, dict) else {},
			todo_brief=[str(t) for t in (raw.get("todo_brief") or [])],
			current_tool=str(raw.get("current_tool") or ""),
			git_op=str(raw.get("git_op") or ""),
			updated_at=float(raw.get("updated_at") or 0.0),
			queued_notices=queues,
		)


class PresenceState:
	"""在场表纯状态与操作（无锁）。memory / file 两后端共用同一逻辑。

	memory 后端直接持有本对象；file 后端每次操作 load 出本对象、操作、save。
	"""

	def __init__(self) -> None:
		# 结构：root -> session_id -> entry
		self.by_root: dict[str, dict[str, SessionPresenceEntry]] = {}
		# 反向索引：session_id -> root（无 cwd 时删除用）
		self.session_root: dict[str, str] = {}

	# -- 序列化 -------------------------------------------------------------

	def to_dict(self) -> dict[str, Any]:
		return {
			"by_root": {
				root: {sid: ent.to_dict() for sid, ent in bucket.items()}
				for root, bucket in self.by_root.items()
			},
			"session_root": dict(self.session_root),
		}

	@classmethod
	def from_dict(cls, raw: dict[str, Any]) -> "PresenceState":
		state = cls()
		if not isinstance(raw, dict):
			return state
		by_root = raw.get("by_root")
		if isinstance(by_root, dict):
			for root, bucket in by_root.items():
				if not isinstance(bucket, dict):
					continue
				entries: dict[str, SessionPresenceEntry] = {}
				for sid, ent_raw in bucket.items():
					if not isinstance(ent_raw, dict):
						continue
					try:
						entries[str(sid)] = SessionPresenceEntry.from_dict(ent_raw)
					except (TypeError, ValueError):
						continue
				if entries:
					state.by_root[str(root)] = entries
		session_root = raw.get("session_root")
		if isinstance(session_root, dict):
			state.session_root = {
				str(k): str(v) for k, v in session_root.items()
				if isinstance(k, str) and isinstance(v, str)
			}
		return state

	# -- 操作 ---------------------------------------------------------------

	def _entry(self, cwd: str, session_id: str, *, title: str = "") -> SessionPresenceEntry:
		root = _norm_root(cwd)
		sid = (session_id or "").strip()
		if not sid:
			raise ValueError("session_id is required")
		bucket = self.by_root.setdefault(root, {})
		ent = bucket.get(sid)
		if ent is None:
			ent = SessionPresenceEntry(
				session_id=sid,
				cwd=root,
				title=(title or "").strip() or sid,
				updated_at=time.time(),
			)
			bucket[sid] = ent
		elif title and title.strip():
			ent.title = title.strip()
		self.session_root[sid] = root
		return ent

	def touch_busy(
		self,
		cwd: str,
		session_id: str,
		*,
		busy: bool,
		title: str = "",
	) -> None:
		ent = self._entry(cwd, session_id, title=title)
		ent.busy = bool(busy)
		ent.updated_at = time.time()
		if not busy:
			ent.current_tool = ""
			ent.git_op = ""

	def note_write(
		self,
		cwd: str,
		session_id: str,
		path: str,
		*,
		title: str = "",
	) -> None:
		rel = _rel_path(_norm_root(cwd), path)
		if not rel:
			return
		ent = self._entry(cwd, session_id, title=title)
		ent.prune_owned()
		ent.owned_files[rel] = time.time()
		# 限幅：保留最近写入
		if len(ent.owned_files) > MAX_OWNED_PATHS:
			ordered = sorted(ent.owned_files.items(), key=lambda kv: kv[1])
			ent.owned_files = dict(ordered[-MAX_OWNED_PATHS:])
		ent.updated_at = time.time()

	def note_git(
		self,
		cwd: str,
		session_id: str,
		op: str | None,
		*,
		title: str = "",
	) -> None:
		ent = self._entry(cwd, session_id, title=title)
		ent.git_op = (op or "").strip()
		ent.updated_at = time.time()

	def note_tool(
		self,
		cwd: str,
		session_id: str,
		tool_name: str,
		*,
		title: str = "",
	) -> None:
		ent = self._entry(cwd, session_id, title=title)
		ent.current_tool = (tool_name or "").strip()
		ent.updated_at = time.time()

	def note_todos(
		self,
		cwd: str,
		session_id: str,
		todos: list[str],
		*,
		title: str = "",
	) -> None:
		briefs = [str(t).strip() for t in (todos or []) if str(t).strip()][:MAX_TODO_BRIEF]
		ent = self._entry(cwd, session_id, title=title)
		ent.todo_brief = briefs
		ent.updated_at = time.time()

	def set_title(self, cwd: str, session_id: str, title: str) -> None:
		ent = self._entry(cwd, session_id, title=title)
		if title.strip():
			ent.title = title.strip()

	def drop(self, session_id: str) -> None:
		sid = (session_id or "").strip()
		if not sid:
			return
		root = self.session_root.pop(sid, None)
		if root is None:
			for r, bucket in list(self.by_root.items()):
				if sid in bucket:
					root = r
					break
		if root is None:
			return
		bucket = self.by_root.get(root)
		if bucket is not None:
			bucket.pop(sid, None)
			if not bucket:
				self.by_root.pop(root, None)

	def clear_owned(self, cwd: str, session_id: str, paths: list[str] | None = None) -> None:
		"""Rewind 成功或用户放弃时清除文件所有权。"""
		root = _norm_root(cwd)
		bucket = self.by_root.get(root)
		if not bucket:
			return
		ent = bucket.get((session_id or "").strip())
		if ent is None:
			return
		if paths is None:
			ent.owned_files.clear()
		else:
			for p in paths:
				rel = _rel_path(root, p)
				ent.owned_files.pop(rel, None)
		ent.updated_at = time.time()

	def queue_notice(self, session_id: str, text: str) -> None:
		msg = (text or "").strip()
		if not msg:
			return
		sid = (session_id or "").strip()
		root = self.session_root.get(sid)
		if root is None:
			return
		ent = self.by_root.get(root, {}).get(sid)
		if ent is None:
			return
		ent.prune_notices()
		ent.queued_notices.append((time.time(), msg))
		ent.queued_notices = ent.queued_notices[-MAX_QUEUED_NOTICES:]
		ent.updated_at = time.time()

	def take_notices(self, session_id: str) -> list[str]:
		sid = (session_id or "").strip()
		root = self.session_root.get(sid)
		if root is None:
			return []
		ent = self.by_root.get(root, {}).get(sid)
		if ent is None:
			return []
		ent.prune_notices()
		out = [text for _t, text in ent.queued_notices]
		ent.queued_notices.clear()
		return out

	def peers(self, cwd: str, self_id: str) -> list[SessionPresenceEntry]:
		"""同工作区其他会话快照（已 prune 过期所有权）。

		同一会话树（主会话 + 其子 agent）不算「其他会话」——与
		``peer_conflict_files`` 对齐，否则自己的子 agent 会以外部会话身份出现。
		"""
		root = _norm_root(cwd)
		sid = (self_id or "").strip()
		self_tree_root = session_tree_root(sid)
		now = time.time()
		bucket = self.by_root.get(root) or {}
		out: list[SessionPresenceEntry] = []
		for other_id, ent in bucket.items():
			if other_id == sid:
				continue
			if session_tree_root(other_id) == self_tree_root:
				continue
			ent.prune_owned(now=now)
			ent.prune_notices(now=now)
			# 无 busy、无 owned、无 git、无 todo 的空壳不返回
			if not (
				ent.busy
				or ent.owned_files
				or ent.git_op
				or ent.todo_brief
			):
				continue
			out.append(
				SessionPresenceEntry(
					session_id=ent.session_id,
					cwd=ent.cwd,
					title=ent.title,
					busy=ent.busy,
					owned_files=dict(ent.owned_files),
					todo_brief=list(ent.todo_brief),
					current_tool=ent.current_tool,
					git_op=ent.git_op,
					updated_at=ent.updated_at,
					queued_notices=list(ent.queued_notices),
				)
			)
		return out

	def self_entry(self, cwd: str, session_id: str) -> SessionPresenceEntry | None:
		root = _norm_root(cwd)
		sid = (session_id or "").strip()
		ent = (self.by_root.get(root) or {}).get(sid)
		if ent is None:
			return None
		ent.prune_owned()
		return SessionPresenceEntry(
			session_id=ent.session_id,
			cwd=ent.cwd,
			title=ent.title,
			busy=ent.busy,
			owned_files=dict(ent.owned_files),
			todo_brief=list(ent.todo_brief),
			current_tool=ent.current_tool,
			git_op=ent.git_op,
			updated_at=ent.updated_at,
			queued_notices=list(ent.queued_notices),
		)

	def owner_of(
		self, cwd: str, path: str, *, exclude_session: str = ""
	) -> SessionPresenceEntry | None:
		"""返回拥有该相对路径且仍在 TTL 内的其他会话（优先 busy）。"""
		root = _norm_root(cwd)
		rel = _rel_path(root, path)
		if not rel:
			return None
		excl = (exclude_session or "").strip()
		now = time.time()
		bucket = self.by_root.get(root) or {}
		busy_hit: SessionPresenceEntry | None = None
		idle_hit: SessionPresenceEntry | None = None
		for sid, ent in bucket.items():
			if sid == excl:
				continue
			ent.prune_owned(now=now)
			ts = ent.owned_files.get(rel)
			if ts is None:
				continue
			snap = SessionPresenceEntry(
				session_id=ent.session_id,
				cwd=ent.cwd,
				title=ent.title,
				busy=ent.busy,
				owned_files={rel: ts},
				todo_brief=list(ent.todo_brief),
				current_tool=ent.current_tool,
				git_op=ent.git_op,
				updated_at=ent.updated_at,
			)
			if ent.busy:
				busy_hit = snap
				break
			if idle_hit is None or ts > next(iter(idle_hit.owned_files.values()), 0):
				idle_hit = snap
		return busy_hit or idle_hit

	def peer_conflict_files(
		self, cwd: str, self_id: str, paths: list[str]
	) -> dict[str, tuple[str, float]]:
		"""本会话触碰过的路径中，由**其他会话树**（root != self root）在 TTL 内
		写入过的：返回 rel_path -> (owner_label, write_ts)。同一会话树内的子 agent
		写入不算外部，不返回。"""
		root = _norm_root(cwd)
		sid = (self_id or "").strip()
		self_root = session_tree_root(sid)
		now = time.time()
		conflicts: dict[str, tuple[str, float]] = {}
		bucket = self.by_root.get(root) or {}
		for other_id, ent in bucket.items():
			if other_id == sid or session_tree_root(other_id) == self_root:
				continue
			ent.prune_owned(now=now)
			label = ent.title or _short_id(ent.session_id)
			for ref in paths:
				rel = _rel_path(root, ref)
				if not rel:
					continue
				ts = ent.owned_files.get(rel)
				if ts is not None and rel not in conflicts:
					conflicts[rel] = (label, ts)
		return conflicts

	def peer_git_conflict(
		self, cwd: str, self_id: str, command: str
	) -> tuple[str, list[str]] | None:
		"""若 git 写操作会交叉其他会话脏文件 / 正在跑的 git，返回 (summary, paths)。"""
		op = detect_git_write_op(command)
		if not op:
			return None
		root = _norm_root(cwd)
		sid = (self_id or "").strip()
		now = time.time()
		bucket = self.by_root.get(root) or {}
		cross_paths: list[str] = []
		owners: list[str] = []
		for other_id, ent in bucket.items():
			if other_id == sid:
				continue
			ent.prune_owned(now=now)
			label = ent.title or _short_id(ent.session_id)
			if ent.git_op:
				owners.append(f"「{label}」正在执行 git {ent.git_op}")
			owned = sorted(ent.owned_files.keys())
			if not owned:
				continue
			if _git_op_touches_all(op, command) or _git_op_may_touch(op, command, owned):
				cross_paths.extend(owned)
				owners.append(f"「{label}」持有: {', '.join(owned[:6])}")
		if not owners:
			return None
		# 去重路径
		seen: list[str] = []
		for p in cross_paths:
			if p not in seen:
				seen.append(p)
		summary = (
			f"Git {op} 与其他会话交叉：\n"
			+ "\n".join(f"- {o}" for o in owners[:8])
		)
		return summary, seen

	def display_title(self, session_id: str) -> str:
		sid = (session_id or "").strip()
		root = self.session_root.get(sid)
		if root is None:
			return _short_id(sid)
		ent = (self.by_root.get(root) or {}).get(sid)
		if ent is None:
			return _short_id(sid)
		return ent.title or _short_id(sid)

	def to_peer_dicts(self, cwd: str, self_id: str = "") -> list[dict[str, Any]]:
		"""人类可见 API 载荷（不含对话正文）。"""
		rows = []
		for ent in self.peers(cwd, self_id):
			rows.append(
				{
					"session_id": ent.session_id,
					"title": ent.title,
					"busy": ent.busy,
					"owned_files": sorted(ent.owned_files.keys()),
					"todo_brief": list(ent.todo_brief),
					"current_tool": ent.current_tool,
					"git_op": ent.git_op,
					"updated_at": ent.updated_at,
				}
			)
		return rows


class SessionPresenceRegistry:
	"""进程内、按工作区根隔离的多会话在场表（memory 后端，默认）。"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._state = PresenceState()

	@property
	def _by_root(self) -> dict[str, dict[str, SessionPresenceEntry]]:
		"""兼容视图（既有测试在锁内拨时间戳用）：代理到状态层。"""
		return self._state.by_root

	def touch_busy(
		self,
		cwd: str,
		session_id: str,
		*,
		busy: bool,
		title: str = "",
	) -> None:
		with self._lock:
			self._state.touch_busy(cwd, session_id, busy=busy, title=title)

	def note_write(
		self,
		cwd: str,
		session_id: str,
		path: str,
		*,
		title: str = "",
	) -> None:
		with self._lock:
			self._state.note_write(cwd, session_id, path, title=title)

	def note_git(
		self,
		cwd: str,
		session_id: str,
		op: str | None,
		*,
		title: str = "",
	) -> None:
		with self._lock:
			self._state.note_git(cwd, session_id, op, title=title)

	def note_tool(
		self,
		cwd: str,
		session_id: str,
		tool_name: str,
		*,
		title: str = "",
	) -> None:
		with self._lock:
			self._state.note_tool(cwd, session_id, tool_name, title=title)

	def note_todos(
		self,
		cwd: str,
		session_id: str,
		todos: list[str],
		*,
		title: str = "",
	) -> None:
		with self._lock:
			self._state.note_todos(cwd, session_id, todos, title=title)

	def set_title(self, cwd: str, session_id: str, title: str) -> None:
		with self._lock:
			self._state.set_title(cwd, session_id, title)

	def drop(self, session_id: str) -> None:
		with self._lock:
			self._state.drop(session_id)

	def clear_owned(self, cwd: str, session_id: str, paths: list[str] | None = None) -> None:
		with self._lock:
			self._state.clear_owned(cwd, session_id, paths)

	def queue_notice(self, session_id: str, text: str) -> None:
		with self._lock:
			self._state.queue_notice(session_id, text)

	def take_notices(self, session_id: str) -> list[str]:
		with self._lock:
			return self._state.take_notices(session_id)

	def peers(self, cwd: str, self_id: str) -> list[SessionPresenceEntry]:
		with self._lock:
			return self._state.peers(cwd, self_id)

	def self_entry(self, cwd: str, session_id: str) -> SessionPresenceEntry | None:
		with self._lock:
			return self._state.self_entry(cwd, session_id)

	def owner_of(
		self, cwd: str, path: str, *, exclude_session: str = ""
	) -> SessionPresenceEntry | None:
		with self._lock:
			return self._state.owner_of(cwd, path, exclude_session=exclude_session)

	def peer_conflict_files(
		self, cwd: str, self_id: str, paths: list[str]
	) -> dict[str, tuple[str, float]]:
		with self._lock:
			return self._state.peer_conflict_files(cwd, self_id, paths)

	def peer_git_conflict(
		self, cwd: str, self_id: str, command: str
	) -> tuple[str, list[str]] | None:
		with self._lock:
			return self._state.peer_git_conflict(cwd, self_id, command)

	def display_title(self, session_id: str) -> str:
		with self._lock:
			return self._state.display_title(session_id)

	def to_peer_dicts(self, cwd: str, self_id: str = "") -> list[dict[str, Any]]:
		with self._lock:
			return self._state.to_peer_dicts(cwd, self_id)


_GIT_WRITE_OPS = frozenset(
	{
		"commit",
		"add",
		"pull",
		"merge",
		"rebase",
		"checkout",
		"switch",
		"reset",
		"stash",
		"push",
	}
)

_GIT_TOUCH_ALL = frozenset(
	{"pull", "merge", "rebase", "reset", "checkout", "switch", "stash", "push"}
)


def detect_git_write_op(command: str) -> str | None:
	"""从 Bash 命令中提取 git 写子命令；非 git 写返回 None。"""
	import re

	text = (command or "").strip()
	if not text:
		return None
	# 粗解析：找 git … <op>
	m = re.search(
		r"(?:^|[;&|]\s*|\n)\s*(?:git(?:\.exe)?)\s+(?:-C\s+\S+\s+)?"
		r"(?:-[^\s]+\s+)*([a-z]+)",
		text,
		re.I,
	)
	if not m:
		return None
	op = m.group(1).lower()
	if op in _GIT_WRITE_OPS:
		return op
	return None


def _git_op_touches_all(op: str, command: str) -> bool:
	if op in _GIT_TOUCH_ALL:
		return True
	if op == "commit":
		# commit -a / -am / --all 会吃掉全部脏文件（短选项可组合）
		import re

		return bool(
			re.search(r"(?:^|\s)--all(?:\s|$)", command or "")
			or re.search(r"(?:^|\s)-[a-zA-Z]*a[a-zA-Z]*(?:\s|$)", command or "")
		)
	if op == "add":
		import re

		# 匹配 git add . / -A / --all / -u
		if re.search(r"(?:^|\s)(-A|--all|-u|--update)(?:\s|$)", command or ""):
			return True
		# 裸 `git add` 或 `git add .`
		if re.search(r"\bgit(?:\.exe)?\s+(?:-C\s+\S+\s+)*add\s+\.(?:\s|$)", command or "", re.I):
			return True
	return False


def _git_op_may_touch(op: str, command: str, owned: list[str]) -> bool:
	"""路径级：命令字面量是否点名了 owned 路径。"""
	if _git_op_touches_all(op, command):
		return True
	low = (command or "").replace("\\", "/").lower()
	for p in owned:
		if p.lower() in low or Path(p).name.lower() in low:
			return True
	return False


def peer_activity_block(cwd: str, self_id: str) -> str:
	"""T_now 块：peer 事件通知 + 一行 presence beacon；无交叉返回空串。

	「其他会话正在聊什么」已工具化：话题与笔记由模型按需
	``Memory(action=peers)`` / ``Memory(action=search)`` 拉取，本块只保留
	- queued notices（事件，drain 语义，取走即清；先过 harvest_sanitize）；
	- 一行 beacon（能力宣告，指向 Memory 工具）；
	- 无条件禁止行（防弱模型把背景信息当任务）。
	"""
	from permissions.policy import side_mode
	from prompt.fence import harvest_sanitize

	if side_mode():
		return ""
	reg = default_session_presence()
	# 先吐出排队通知（事件绝不静默：取走即清，静默即永久丢失）。
	notices = [harvest_sanitize(n) for n in reg.take_notices(self_id)]
	peers = reg.peers(cwd, self_id)
	if not peers and not notices:
		return ""
	lines = ["# 其他会话活动（background only）"]
	for n in notices:
		n = n.strip()
		if n:
			lines.append(n)
	if peers:
		# C4 裁决：只陈述事实；查看指引放 Memory 工具 description，不放这里。
		lines.append(f"同工作区另有 {len(peers)} 个会话运行中。")
	return "\n".join(lines)


def format_peer_file_prompt(owner: SessionPresenceEntry, path: str) -> str:
	label = owner.title or _short_id(owner.session_id)
	rel = path.replace("\\", "/")
	return (
		f"文件 `{rel}` 正由会话「{label}」持有（忙碌中）。\n"
		"请选择：硬拦（不写）/ 提醒双方后取消 / 继续写入。"
	)


def format_stale_owner_hint(cwd: str, path: str) -> str:
	reg = default_session_presence()
	owner = reg.owner_of(cwd, path)
	if owner is None:
		return ""
	label = owner.title or _short_id(owner.session_id)
	return f" Last writer appears to be session 「{label}」 ({_short_id(owner.session_id)})."


_default_presence: Any | None = None
_presence_lock = threading.Lock()


class _DispatchPresence:
	"""按 cwd 动态分派后端：workspace 级配置生效，判定结果按 root 缓存。

	无 cwd 方法（drop / queue_notice / take_notices / display_title）：
	file 索引里能反查到 root → 走 file 后端；否则走 memory 单例（兼容现状）。
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._memory: SessionPresenceRegistry | None = None
		self._file: Any | None = None
		self._by_root: dict[str, Any] = {}

	def _memory_single(self) -> SessionPresenceRegistry:
		if self._memory is None:
			self._memory = SessionPresenceRegistry()
		return self._memory

	def _file_single(self) -> Any:
		if self._file is None:
			from coord.presence_adapter import FileBackedPresence

			self._file = FileBackedPresence()
		return self._file

	def _for_cwd(self, cwd: str | Path) -> Any:
		if not (cwd or "").strip():
			return self._memory_single()
		root = _norm_root(cwd)
		with self._lock:
			hit = self._by_root.get(root)
			if hit is None:
				try:
					from coord.config import coord_backend

					backend = coord_backend(str(cwd))
				except Exception:
					backend = "memory"
				hit = self._file_single() if backend == "file" else self._memory_single()
				self._by_root[root] = hit
			return hit

	def _file_if_known(self, session_id: str) -> Any | None:
		"""session_id 在 file 索引里有 root → file 后端；否则 None。"""
		try:
			file_be = self._file_single()
			if file_be.knows_session(session_id):
				return file_be
		except Exception:
			return None
		return None

	# -- 带 cwd：直接按 root 分派 -------------------------------------------

	def touch_busy(self, cwd: str, session_id: str, *, busy: bool, title: str = "") -> None:
		self._for_cwd(cwd).touch_busy(cwd, session_id, busy=busy, title=title)

	def note_write(self, cwd: str, session_id: str, path: str, *, title: str = "") -> None:
		self._for_cwd(cwd).note_write(cwd, session_id, path, title=title)

	def note_git(self, cwd: str, session_id: str, op: str | None, *, title: str = "") -> None:
		self._for_cwd(cwd).note_git(cwd, session_id, op, title=title)

	def note_tool(self, cwd: str, session_id: str, tool_name: str, *, title: str = "") -> None:
		self._for_cwd(cwd).note_tool(cwd, session_id, tool_name, title=title)

	def note_todos(self, cwd: str, session_id: str, todos: list[str], *, title: str = "") -> None:
		self._for_cwd(cwd).note_todos(cwd, session_id, todos, title=title)

	def set_title(self, cwd: str, session_id: str, title: str) -> None:
		self._for_cwd(cwd).set_title(cwd, session_id, title)

	def clear_owned(self, cwd: str, session_id: str, paths: list[str] | None = None) -> None:
		self._for_cwd(cwd).clear_owned(cwd, session_id, paths)

	def peers(self, cwd: str, self_id: str) -> list[SessionPresenceEntry]:
		return self._for_cwd(cwd).peers(cwd, self_id)

	def self_entry(self, cwd: str, session_id: str) -> SessionPresenceEntry | None:
		return self._for_cwd(cwd).self_entry(cwd, session_id)

	def owner_of(self, cwd: str, path: str, *, exclude_session: str = "") -> SessionPresenceEntry | None:
		return self._for_cwd(cwd).owner_of(cwd, path, exclude_session=exclude_session)

	def peer_conflict_files(self, cwd: str, self_id: str, paths: list[str]) -> dict[str, tuple[str, float]]:
		return self._for_cwd(cwd).peer_conflict_files(cwd, self_id, paths)

	def peer_git_conflict(self, cwd: str, self_id: str, command: str) -> tuple[str, list[str]] | None:
		return self._for_cwd(cwd).peer_git_conflict(cwd, self_id, command)

	def to_peer_dicts(self, cwd: str, self_id: str = "") -> list[dict[str, Any]]:
		return self._for_cwd(cwd).to_peer_dicts(cwd, self_id)

	# -- 无 cwd：索引反查 ----------------------------------------------------

	def drop(self, session_id: str) -> None:
		be = self._file_if_known(session_id)
		if be is not None:
			be.drop(session_id)
			return
		self._memory_single().drop(session_id)

	def queue_notice(self, session_id: str, text: str) -> None:
		be = self._file_if_known(session_id)
		if be is not None:
			be.queue_notice(session_id, text)
			return
		self._memory_single().queue_notice(session_id, text)

	def take_notices(self, session_id: str) -> list[str]:
		be = self._file_if_known(session_id)
		if be is not None:
			return be.take_notices(session_id)
		return self._memory_single().take_notices(session_id)

	def display_title(self, session_id: str) -> str:
		be = self._file_if_known(session_id)
		if be is not None:
			return be.display_title(session_id)
		return self._memory_single().display_title(session_id)


def default_session_presence() -> Any:
	"""进程级入口：默认直连 memory 单例（现状路径，零分派开销）；
	coord 配置为 file 时返回按 cwd 分派的门面。"""
	global _default_presence
	with _presence_lock:
		if _default_presence is None:
			try:
				from coord.config import coord_backend

				probe = coord_backend()
			except Exception:
				probe = "memory"
			if probe == "memory":
				_default_presence = SessionPresenceRegistry()
			else:
				_default_presence = _DispatchPresence()
		return _default_presence


def reset_session_presence_for_tests() -> SessionPresenceRegistry:
	"""测试用：清空并返回新注册表（memory 后端）。"""
	global _default_presence
	with _presence_lock:
		_default_presence = SessionPresenceRegistry()
		return _default_presence  # type: ignore[return-value]


__all__ = [
	"FILE_OWNERSHIP_TTL_SEC",
	"PEER_CHOICES",
	"PresenceState",
	"SessionPresenceEntry",
	"SessionPresenceRegistry",
	"default_session_presence",
	"detect_git_write_op",
	"format_peer_file_prompt",
	"format_stale_owner_hint",
	"peer_activity_block",
	"reset_session_presence_for_tests",
	"session_tree_root",
]
