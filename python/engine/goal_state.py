"""Goal 状态机实体 + 持久化存储（T9，按 docs 详设定稿）。

设计要点（节选自 docs/XEYO-融合改造计划.md §T9 详设）：
- 实体 ``Goal{goal_id,title,text,status,owner,origin,pending_complete,revision}``；
  4 态 ``active/blocked/completed/abandoned`` + **派生候选 ``pending_complete``**（非终态，仍 active）。
- 存储 ``<workspace>/.xeyo/goals/goals/<goal_id>.json`` + ``bindings/<safe_session_id>.json``；
  tmp + ``os.replace`` 原子写；坏文件跳过。
- 并发：per-workspace asyncio 锁 + ``WorkspaceLock`` 跨进程短租约 + **PATCH revision CAS**
  （miss -> ``409 goal_revision_conflict``，body 附当前 goal 供刷新；禁盲写）。
- 降级铁律：锁/文件/坏 JSON 一律 try/except + log，失败只降级不挡主路径。
- **armed 激活只在内存**：进程重启绝不自动续跑（本模块只落盘状态，trigger 由外层决定）。
- **41 号语义**：round 数只由 round driver 的 ``admit_round_async`` 推进（合成轮真正
  被引擎接受才计，预约作废不消耗），人类轮不消耗 cap；turn 终态钩子只做候选派生
  （``mark_candidate_async``，无变化不写不 bump revision）；blocked 转换带
  ``blocked_reason``（补 38 号触发点 #2 记账）。

本模块只做实体/状态机/存储；外层钩子（chat.py submit 建绑定、turn_runner 失败 blocked、
resume cue 恢复）与 HTTP API 见调用方。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger("xeyo.goal")

# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_BLOCKED = "blocked"
STATUS_COMPLETED = "completed"
STATUS_ABANDONED = "abandoned"
STATUSES: tuple[str, ...] = (
	STATUS_ACTIVE,
	STATUS_PAUSED,
	STATUS_BLOCKED,
	STATUS_COMPLETED,
	STATUS_ABANDONED,
)

# 合法转换表（非法转换拒绝并记日志，不影响 turn 主路径）。pending_complete 是
# active 上的派生候选标志，不是独立状态；何时确认完结由外层决定。
# 41 号扩展：新增 paused（DSH 对齐 —— 持久暂停相；paused 不自动续跑）。
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
	STATUS_ACTIVE: frozenset({STATUS_BLOCKED, STATUS_COMPLETED, STATUS_ABANDONED, STATUS_PAUSED}),
	STATUS_PAUSED: frozenset({STATUS_ACTIVE, STATUS_ABANDONED}),
	STATUS_BLOCKED: frozenset({STATUS_ACTIVE, STATUS_ABANDONED}),
	STATUS_COMPLETED: frozenset(),
	STATUS_ABANDONED: frozenset({STATUS_ACTIVE}),  # reopen
}

_REVISION_CONFLICT = "goal_revision_conflict"

# 软 cap：goal 轮次达此值仍 active（未人为确认）→ 置 pending_complete（候选，
# 让模型/用户确认），而非硬停 turn（goal 层不做执行控制——见 38 号 §刻意不做）。
GOAL_ROUND_CAP = 32


@dataclass
class Goal:
	goal_id: str
	title: str
	text: str
	status: str = STATUS_ACTIVE
	owner: str = ""
	origin: str = ""
	# 派生候选标志：仍在 active，但满足候选（如 todos all done / subagent all_succeeded）。
	pending_complete: bool = False
	revision: int = 1
	# 已推进的 goal 轮次（round 数只由 goal 轮推进；软 cap，超 cap 置候选而非硬停）。
	# 41 号语义修正：只由 round driver 的 admit_round 推进——人类轮不消耗 cap。
	rounds: int = 1
	# per-goal 轮次上限（41 号）：0 = 回落全局默认（config goal_round_cap / GOAL_ROUND_CAP）。
	max_rounds: int = 0
	# blocked 原因（41 号补记账，38 号触发点 #2）：置 blocked 时写入，恢复 active 清空。
	blocked_reason: str = ""
	created_at: float = 0.0
	updated_at: float = 0.0

	def to_dict(self) -> dict[str, Any]:
		return {
			"goal_id": self.goal_id,
			"title": self.title,
			"text": self.text,
			"status": self.status,
			"owner": self.owner,
			"origin": self.origin,
			"pending_complete": bool(self.pending_complete),
			"revision": int(self.revision),
			"rounds": int(self.rounds),
			"max_rounds": int(self.max_rounds),
			"blocked_reason": str(self.blocked_reason or ""),
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}

	@classmethod
	def from_dict(cls, raw: dict[str, Any]) -> "Goal":
		status = str(raw.get("status") or STATUS_ACTIVE)
		if status not in STATUSES:
			status = STATUS_ACTIVE
		try:
			_max_rounds = int(raw.get("max_rounds") or 0)
		except (TypeError, ValueError):
			_max_rounds = 0
		return cls(
			goal_id=str(raw.get("goal_id") or ""),
			title=str(raw.get("title") or ""),
			text=str(raw.get("text") or ""),
			status=status,
			owner=str(raw.get("owner") or ""),
			origin=str(raw.get("origin") or ""),
			pending_complete=bool(raw.get("pending_complete")),
			revision=max(1, int(raw.get("revision") or 1)),
			rounds=max(1, int(raw.get("rounds") or 1)),
			max_rounds=max(0, _max_rounds),
			blocked_reason=str(raw.get("blocked_reason") or ""),
			created_at=float(raw.get("created_at") or 0.0),
			updated_at=float(raw.get("updated_at") or 0.0),
		)


def can_transition(current: str, target: str) -> bool:
	"""target 对 current 是否合法转换（pending_complete 为标志，不参与转换判定）。"""
	if current not in _LEGAL_TRANSITIONS:
		return False
	return target in _LEGAL_TRANSITIONS[current]


# 候选派生状态（T9 P1）：由引擎钩子用信号算出，决定是否置 pending_complete。
CANDIDATE_ACTIVE = "active"
CANDIDATE_TODOS_DONE = "todos_all_done"
CANDIDATE_BATCH_AWAITING_SYNTHESIS = "batch_awaiting_synthesis"
CANDIDATE_SYNTHESIS_DONE = "synthesis_done"


def derive_candidate(
	*,
	turn_succeeded: bool = False,
	todos_all_done: bool = False,
	multi_agent_all_succeeded: bool = False,
	synthesis_succeeded: bool = False,
) -> str:
	"""按信号派生候选状态（无候选返回 active）。

	优先级：todos 全 done > 多 Agent all_succeeded > synthesis succeeded。
	"""
	if turn_succeeded and todos_all_done:
		return CANDIDATE_TODOS_DONE
	if multi_agent_all_succeeded:
		return CANDIDATE_BATCH_AWAITING_SYNTHESIS
	if synthesis_succeeded:
		return CANDIDATE_SYNTHESIS_DONE
	return CANDIDATE_ACTIVE


def candidate_is_pending(candidate: str) -> bool:
	"""候选状态是否应置 pending_complete=True。"""
	return candidate != CANDIDATE_ACTIVE


def resolved_max_rounds(goal: Goal, default_cap: int = GOAL_ROUND_CAP) -> int:
	"""per-goal 轮次上限解析（41 号）：goal.max_rounds > 0 优先，否则全局默认。"""
	try:
		per = int(goal.max_rounds or 0)
	except (TypeError, ValueError):
		per = 0
	if per > 0:
		return per
	try:
		return max(1, int(default_cap or GOAL_ROUND_CAP))
	except (TypeError, ValueError):
		return GOAL_ROUND_CAP


def _previous_user_goal(messages: list[dict]) -> str:
	"""取最后一条带实质内容的 user 消息作为目标文本（跳过续跑口令/空文本）。

	与 server/routers/chat.py 的 ``_previous_user_goal`` 对齐（独立的轻量实现，
	避免跨模块循环依赖）。
	"""
	seen_latest = False
	for m in reversed(messages):
		if (m.get("role") or m.get("type")) != "user":
			continue
		content = m.get("content")
		if isinstance(content, list):
			parts = [
				str(b.get("text") or "")
				for b in content
				if isinstance(b, dict) and b.get("type") == "text"
			]
			text = "\n".join(parts)
		else:
			text = str(content or "")
		text = text.strip()
		if not text:
			continue
		if not seen_latest:
			seen_latest = True
			continue
		return text
	return ""


def resolve_session_goal(
	store: GoalStore, session_id: str, messages: list[dict]
) -> tuple[Goal | None, str]:
	"""resume 链三级兜底（T9）：绑定当前 > 上一个实质用户目标。

	返回 ``(goal, source)``；source ∈ {``bind``, ``derived``, ``none``}。
	derived 时并不落盘（懒采纳），仅返回根据消息文本构造的目标供消费方决定。
	"""
	g = store.current(session_id)
	if g is not None:
		return g, "bind"
	text = _previous_user_goal(messages)
	if text:
		return (
			Goal(goal_id="", title=text[:48], text=text, origin="resume_derived"),
			"derived",
		)
	return None, "none"


def _safe_session_id(session_id: str) -> str:
	"""把 session_id 清洗成安全文件名（新方案：可读前缀 + sha1 摘要，防碰撞）。

	2026-09-05 修正：旧方案把所有非字母数字替换成 '_'，不同 session_id
	（如 ``a-1`` 与 ``a_1``）会碰撞到同一 binding 文件（跨会话串绑）。
	新方案保留 ``[A-Za-z0-9_-]`` 前缀 + 原始 id 的 sha1 前 10 位。
	"""
	import hashlib

	raw = (session_id or "anon").encode("utf-8")
	base = "".join(
		ch if (ch.isalnum() or ch in "-_") else "_" for ch in (session_id or "anon")
	)[:48]
	return f"{base}-{hashlib.sha1(raw).hexdigest()[:10]}"


def _legacy_safe_session_id(session_id: str) -> str:
	"""旧版清洗（2026-09-05 前）：只作旧 binding 文件的**读取回退**。"""
	return "".join(ch if ch.isalnum() else "_" for ch in (session_id or "anon"))[:64]


class GoalConflict(Exception):
	"""revision CAS 冲突（409）。"""

	def __init__(self, goal: Goal) -> None:
		self.goal = goal
		super().__init__(_REVISION_CONFLICT)


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
class GoalStore:
	"""按 workspace 的 goal 持久化 + 绑定（并发三层里的锁/CAS 落在这里）。

	锁注册表为**模块级**（2026-09-05 修正：旧实现锁挂在实例上，而 driver /
	routers / query_engine 各自 new GoalStore——实例级锁互不认识，「进程内
	互斥」是错觉）。现按 ``workspace|key`` 全局取锁，跨实例真互斥；
	跨进程仍由调用方叠加 WorkspaceLock（goal 文件有 revision CAS 兜底）。
	"""

	#: 模块级锁注册表：key = f"{workspace}|{lock_key}"（跨实例共享）。
	_GLOBAL_LOCKS: dict[str, asyncio.Lock] = {}

	def __init__(self, workspace: str) -> None:
		self._root = Path(workspace) / ".xeyo" / "goals"
		self._goals_dir = self._root / "goals"
		self._bindings_dir = self._root / "bindings"
		self._workspace = str(workspace)

	def _lock_for(self, key: str) -> asyncio.Lock:
		gkey = f"{self._workspace}|{key}"
		lock = GoalStore._GLOBAL_LOCKS.get(gkey)
		if lock is None:
			lock = asyncio.Lock()
			GoalStore._GLOBAL_LOCKS[gkey] = lock
		return lock

	def reset_locks(self) -> None:
		GoalStore._GLOBAL_LOCKS.clear()

	# -- 低层原子读写 -------------------------------------------------------
	def _goal_path(self, goal_id: str) -> Path:
		return self._goals_dir / f"{goal_id}.json"

	def _binding_path(self, session_id: str) -> Path:
		return self._bindings_dir / f"{_safe_session_id(session_id)}.json"

	def _binding_path_candidates(self, session_id: str) -> list[Path]:
		"""binding 文件候选：新命名优先，旧命名作读取回退（命名迁移兼容）。"""
		return [
			self._bindings_dir / f"{_safe_session_id(session_id)}.json",
			self._bindings_dir / f"{_legacy_safe_session_id(session_id)}.json",
		]

	def _read_json(self, path: Path) -> dict[str, Any] | None:
		try:
			if not path.is_file():
				return None
			raw = json.loads(path.read_text(encoding="utf-8"))
			return raw if isinstance(raw, dict) else None
		except Exception as exc:  # noqa: BLE001
			_logger.warning("goal store read failed %s: %s", path, exc)
			return None

	def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
		path.parent.mkdir(parents=True, exist_ok=True)
		fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
		try:
			with os.fdopen(fd, "w", encoding="utf-8") as fh:
				json.dump(data, fh, ensure_ascii=False)
				fh.flush()
			os.replace(tmp, path)
		except Exception:  # noqa: BLE001
			try:
				os.unlink(tmp)
			except OSError:
				pass
			raise

	# -- CRUD --------------------------------------------------------------
	def get(self, goal_id: str) -> Goal | None:
		raw = self._read_json(self._goal_path(goal_id))
		if raw is None:
			return None
		g = Goal.from_dict(raw)
		return g if g.goal_id else None

	def create(
		self,
		*,
		title: str,
		text: str,
		owner: str = "",
		origin: str = "",
		goal_id: str | None = None,
		pending_complete: bool = False,
	) -> Goal:
		now = 0.0
		try:
			import time

			now = time.time()
		except Exception:  # noqa: BLE001
			pass
		goal = Goal(
			goal_id=goal_id or uuid.uuid4().hex[:12],
			title=title,
			text=text,
			owner=owner,
			origin=origin,
			pending_complete=pending_complete,
			revision=1,
			created_at=now,
			updated_at=now,
		)
		self._run(self._create_async(goal))
		return goal

	async def _create_async(self, goal: Goal) -> None:
		async with self._lock_for(goal.goal_id):
			self._atomic_write_json(self._goal_path(goal.goal_id), goal.to_dict())

	def load(self, goal_id: str) -> Goal | None:
		return self.get(goal_id)

	def list_all(self) -> list[Goal]:
		out: list[Goal] = []
		try:
			if self._goals_dir.is_dir():
				for p in self._goals_dir.glob("*.json"):
					g = self.get(p.stem)
					if g:
						out.append(g)
		except OSError:
			pass
		out.sort(key=lambda g: g.updated_at, reverse=True)
		return out

	def transition(
		self,
		goal_id: str,
		target: str,
		*,
		revision: int | None = None,
		set_pending_complete: bool | None = None,
		blocked_reason: str = "",
	) -> Goal:
		"""状态转换（revision 传入则做 CAS：不符抛 GoalConflict）。

		非法转换：记日志并返回当前 goal（不抛、不写）。CAS miss：抛 GoalConflict。
		target=blocked 时 blocked_reason 落盘（41 号补记账）；恢复 active 自动清空。
		"""
		return self._run(
			self._transition_async(
				goal_id, target, revision, set_pending_complete, blocked_reason
			)
		)

	async def transition_async(
		self,
		goal_id: str,
		target: str,
		*,
		revision: int | None = None,
		set_pending_complete: bool | None = None,
		blocked_reason: str = "",
	) -> Goal:
		"""``transition`` 的 async 版（运行事件循环内的调用方——如 driver——使用）。"""
		return await self._transition_async(
			goal_id, target, revision, set_pending_complete, blocked_reason
		)

	async def _transition_async(
		self,
		goal_id: str,
		target: str,
		revision: int | None,
		set_pending_complete: bool | None,
		blocked_reason: str = "",
	) -> Goal:
		async with self._lock_for(goal_id):
			goal = self.get(goal_id)
			if goal is None:
				raise KeyError(f"goal not found: {goal_id}")
			if revision is not None and revision != goal.revision:
				raise GoalConflict(goal)
			# 2026-09-05 修正：同状态且候选标志无变化 → no-op 返回（不写盘、
			# 不 bump revision）。旧行为同状态重写也 bump，每次 failed turn 的
			# blocked→blocked 都会空转 GUI 持有的 CAS ref。
			if (
				target == goal.status
				and (
					set_pending_complete is None
					or bool(set_pending_complete) == goal.pending_complete
				)
			):
				return goal
			if target != goal.status and not can_transition(goal.status, target):
				_logger.warning(
					"goal %s illegal transition %s -> %s", goal_id, goal.status, target
				)
				return goal
			goal.status = target
			goal.revision += 1
			if set_pending_complete is not None:
				goal.pending_complete = bool(set_pending_complete)
			# 41 号：blocked 必带原因（补 38 号触发点 #2 记账）；恢复 active 清空。
			if target == STATUS_BLOCKED:
				goal.blocked_reason = (blocked_reason or "").strip() or "turn_failed"
			elif target == STATUS_ACTIVE:
				goal.blocked_reason = ""
			try:
				import time

				goal.updated_at = time.time()
			except Exception:  # noqa: BLE001
				pass
			self._atomic_write_json(self._goal_path(goal_id), goal.to_dict())
			return goal

	# -- session 绑定 -------------------------------------------------------
	def bind(self, session_id: str, goal_id: str) -> None:
		self._run(self._bind_async(session_id, goal_id))

	async def _bind_async(self, session_id: str, goal_id: str) -> None:
		path = self._binding_path(session_id)
		async with self._lock_for("bind:" + _safe_session_id(session_id)):
			self._atomic_write_json(path, {"session_id": session_id, "goal_id": goal_id})

	async def create_and_bind_async(
		self,
		*,
		title: str,
		text: str,
		session_id: str,
		owner: str = "",
		origin: str = "",
		goal_id: str | None = None,
		pending_complete: bool = False,
	) -> Goal:
		"""单个持锁事务内 create + bind（供 async 调用方——如 server 请求——使用）。

		与同步 ``create`` + ``bind`` 等价，但避免在运行事件循环内触发
		``_run`` 的 RuntimeError（同步 API 在循环内会明确报错，见 ``_run``）。
		"""
		now = 0.0
		try:
			import time

			now = time.time()
		except Exception:  # noqa: BLE001
			pass
		goal = Goal(
			goal_id=goal_id or uuid.uuid4().hex[:12],
			title=title,
			text=text,
			owner=owner,
			origin=origin,
			pending_complete=pending_complete,
			revision=1,
			rounds=1,
			created_at=now,
			updated_at=now,
		)
		async with self._lock_for(goal.goal_id):
			self._atomic_write_json(self._goal_path(goal.goal_id), goal.to_dict())
		await self._bind_async(session_id, goal.goal_id)
		return goal

	async def admit_round_async(
		self,
		goal_id: str,
		*,
		revision: int | None = None,
		cap: int = GOAL_ROUND_CAP,
	) -> Goal:
		"""driver 准入一个 goal 轮（41 号）：CAS + rounds+1；超 cap 软置候选。

		round 数只由此推进（人类轮不消耗 cap）；调用时机 = 合成轮真正被引擎接受
		（turn start 成功）之后——预约作废 / 409 / 让位都不消耗轮号。CAS miss 抛
		GoalConflict。非 active 目标 no-op 返回当前 goal。
		"""
		async with self._lock_for(goal_id):
			goal = self.get(goal_id)
			if goal is None:
				raise KeyError(f"goal not found: {goal_id}")
			if revision is not None and revision != goal.revision:
				raise GoalConflict(goal)
			# 只有 active 目标推进轮次；终态 / blocked / abandoned 不再计轮。
			if goal.status != STATUS_ACTIVE:
				return goal
			goal.rounds += 1
			goal.revision += 1
			# cap 安全阀：准入后超出 cap 且仍未确认 → 置候选（软信号，不硬停）。
			if goal.rounds > max(1, int(cap)) and not goal.pending_complete:
				goal.pending_complete = True
			try:
				import time

				goal.updated_at = time.time()
			except Exception:  # noqa: BLE001
				pass
			self._atomic_write_json(self._goal_path(goal_id), goal.to_dict())
			return goal

	async def mark_candidate_async(
		self,
		goal_id: str,
		*,
		revision: int | None = None,
		pending_complete: bool = False,
	) -> Goal:
		"""turn 终态候选派生（41 号）：CAS 写 pending_complete。

		与 admit_round 的分工：本方法只写候选标志、**不推进轮次**（人类轮不消耗
		cap）；标志无变化时不写盘、不 bump revision（GUI 持有的 CAS ref 不被
		无谓失效）。CAS miss 抛 GoalConflict。
		"""
		async with self._lock_for(goal_id):
			goal = self.get(goal_id)
			if goal is None:
				raise KeyError(f"goal not found: {goal_id}")
			if revision is not None and revision != goal.revision:
				raise GoalConflict(goal)
			new_flag = bool(pending_complete)
			# 终态不写；标志无变化不写（revision 稳定，GUI ref 不失效）。
			if goal.status != STATUS_ACTIVE or goal.pending_complete == new_flag:
				return goal
			goal.pending_complete = new_flag
			goal.revision += 1
			try:
				import time

				goal.updated_at = time.time()
			except Exception:  # noqa: BLE001
				pass
			self._atomic_write_json(self._goal_path(goal_id), goal.to_dict())
			return goal

	def update(
		self,
		goal_id: str,
		*,
		revision: int | None = None,
		title: str | None = None,
		text: str | None = None,
		max_rounds: int | None = None,
	) -> Goal:
		"""additive 字段编辑（41 号 PATCH action=edit / arm 携带 max_rounds）。同步包装。"""
		return self._run(
			self.update_async(
				goal_id,
				revision=revision,
				title=title,
				text=text,
				max_rounds=max_rounds,
			)
		)

	async def update_async(
		self,
		goal_id: str,
		*,
		revision: int | None = None,
		title: str | None = None,
		text: str | None = None,
		max_rounds: int | None = None,
	) -> Goal:
		"""字段编辑（CAS）：title / text / max_rounds；无变化不写不 bump revision。"""
		async with self._lock_for(goal_id):
			goal = self.get(goal_id)
			if goal is None:
				raise KeyError(f"goal not found: {goal_id}")
			if revision is not None and revision != goal.revision:
				raise GoalConflict(goal)
			changed = False
			if title is not None:
				new_title = str(title).strip()[:200]
				if new_title and new_title != goal.title:
					goal.title = new_title
					changed = True
			if text is not None:
				new_text = str(text).strip()[:4000]
				if new_text and new_text != goal.text:
					goal.text = new_text
					changed = True
			if max_rounds is not None:
				try:
					new_cap = max(0, int(max_rounds))
				except (TypeError, ValueError):
					new_cap = 0
				if new_cap != goal.max_rounds:
					goal.max_rounds = new_cap
					changed = True
			if not changed:
				return goal
			goal.revision += 1
			try:
				import time

				goal.updated_at = time.time()
			except Exception:  # noqa: BLE001
				pass
			self._atomic_write_json(self._goal_path(goal_id), goal.to_dict())
			return goal

	def unbind(self, session_id: str) -> None:
		self._run(self._unbind_async(session_id))

	async def _unbind_async(self, session_id: str) -> None:
		async with self._lock_for("bind:" + _safe_session_id(session_id)):
			for path in self._binding_path_candidates(session_id):
				try:
					if path.is_file():
						os.unlink(path)
				except OSError:
					pass

	def current(self, session_id: str) -> Goal | None:
		"""当前会话绑定的 goal；无绑定/绑定丢失/坏文件 -> None。

		binding 读取带旧命名回退（2026-09-05 命名迁移：读到旧文件即视同有效，
		下次 bind 会落到新命名）。
		"""
		raw: dict[str, Any] | None = None
		for path in self._binding_path_candidates(session_id):
			raw = self._read_json(path)
			if raw is not None:
				break
		if raw is None:
			return None
		goal_id = str(raw.get("goal_id") or "")
		if not goal_id:
			return None
		return self.get(goal_id)

	@staticmethod
	def _run(coro):
		"""同步执行一个异步操作（无运行循环时用 asyncio.run 阻塞完成）。

		若已在运行事件循环内，直接 await 对应的 ``_xxx_async``（此处显式报错，
		避免 silent 不落盘）。
		"""
		try:
			asyncio.get_running_loop()
		except RuntimeError:
			return asyncio.run(coro)
		raise RuntimeError(
			"GoalStore sync API used inside a running event loop; "
			"await the corresponding *_async method instead."
		)
