"""Job Registry（42 号 P0）— 进程内后台任务注册表 + 完成通知管线。

后台任务语义（42 号 §4/§6）：

- **内存态、per-session（owner）**：进程重启即清空（与 41 号 armed 同纪律）。
- **owner 即安全边界**：list/read/kill 只作用 caller 自会话任务，无 scope 分层。
- **容量 10**：running+stopping 计数；满则在生产方执行前失败，文案教模型 job_kill。
- **首次结算优先**：done / 取消 / 异常竞态只记一次（RLock + status 单向门）。
- **ring 输出**：cap 保尾 + 绝对偏移游标；``job_output`` 单游标增量消费；终态读幂等。
- **通知即输入**：唯一主动通道 = 唤醒轮（复用 41 号合成轮通道，``server/
  synthetic_round.submit_synthetic``）；被动通道 = 人类下一轮 T_now 补投。
- **共享唤醒预算**：``maxConsecutiveWakes=3`` per-session，goal 轮与 job 唤醒共用
  （§3.4 互激防护）；只有人类输入恢复预算（``restore_wake``）。
- **reported 抑制**：kill / 终态 read / 唤醒消费，任一路径置位后不再投递。
- 结算顺序：记录提交 → 可见集变更广播 → 通知决策（投递方可能同步开轮）。

全路径 try/except 降级：注册表任何异常只记日志，绝不影响 turn 与人类请求。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_logger = logging.getLogger("xeyo.jobs")

#: per-session 唤醒预算（42 号 §3.4；goal 轮与 job 唤醒共享）。
MAX_CONSECUTIVE_WAKES = 3
#: 单 owner 并发上限（running+stopping）；满则 start 前失败。
MAX_CONCURRENT_JOBS_PER_OWNER = 10
#: ring 缓冲 cap（字符，保尾）。开放问题 #3：先取 12 号 spill 同量级的常数。
RING_CAP_CHARS = 16_000
#: 后台命令不适用超时（冻结口径：后台语义）；给 24h 物理上限防僵尸。
JOB_NO_TIMEOUT_MS = 86_400_000
#: 唤醒决策防抖（与 41 号同款，给人类消息留让位窗口）。
_WAKE_DEBOUNCE_S = 2.0

STATUS_RUNNING = "running"
STATUS_STOPPING = "stopping"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_KILLED = "killed"
_TERMINAL = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_KILLED})

PushFn = Callable[[str], None]
ProducerFn = Callable[[PushFn], tuple[str, str]]


class _Ring:
	"""cap 保尾文本环 + 绝对偏移游标（UTF-8 安全：按字符计）。"""

	def __init__(self, cap: int = RING_CAP_CHARS) -> None:
		self._cap = max(256, int(cap))
		self._buf: list[str] = []
		self._len = 0
		self._start = 0  # ring[0] 的绝对偏移

	def push(self, text: str) -> None:
		if not text:
			return
		self._buf.append(text)
		self._len += len(text)
		if self._len > self._cap:
			drop = self._len - self._cap
			while self._buf and drop > 0:
				head = self._buf[0]
				if len(head) <= drop:
					drop -= len(head)
					self._buf.pop(0)
				else:
					self._buf[0] = head[drop:]
					drop = 0
			dropped = self._len - sum(len(s) for s in self._buf)
			self._start += dropped
			self._len -= dropped

	def read(self, cursor: int) -> tuple[str, int, bool]:
		"""返回 (增量文本, 新游标, 是否有早期内容被丢弃)。"""
		start = max(int(cursor), self._start)
		truncated = int(cursor) < self._start
		if start >= self._start + self._len:
			return "", max(int(cursor), self._start + self._len), truncated
		text = "".join(self._buf)[start - self._start :]
		return text, self._start + self._len, truncated


@dataclass
class JobRecord:
	job_id: str
	kind: str
	label: str
	owner_session_id: str
	status: str = STATUS_RUNNING
	detail: str = ""
	reported: bool = False
	started_at: float = field(default_factory=time.time)
	finished_at: float = 0.0

	def to_dict(self) -> dict[str, Any]:
		return {
			"job_id": self.job_id,
			"kind": self.kind,
			"label": self.label,
			"status": self.status,
			"detail": self.detail,
			"reported": self.reported,
			"started_at": self.started_at,
			"finished_at": self.finished_at,
		}


def _turn_running(session_id: str) -> bool:
	try:
		from engine.turn_runner import get_turn_runner

		return bool(get_turn_runner().is_running(session_id))
	except Exception:  # noqa: BLE001
		return False


class JobRegistry:
	"""单 server 单组合；线程安全（Bash worker 线程结算 → RLock + loop 代理）。"""

	def __init__(self) -> None:
		self._jobs: dict[str, JobRecord] = {}
		self._rings: dict[str, _Ring] = {}
		self._cursors: dict[str, int] = {}
		self._aborts: dict[str, Any] = {}
		self._counter = 0
		self._lock = threading.RLock()
		self._loops: dict[str, asyncio.AbstractEventLoop] = {}
		# 通知管线状态（per-owner）
		self._wake_budget: dict[str, int] = {}
		self._pending: dict[str, list[str]] = {}
		self._wake_tasks: dict[str, asyncio.Task] = {}
		# 监听：on_done(快照) / on_changed()——hub 与 SSE 广播各挂一个，异常隔离。
		self.on_done: list[Callable[[JobRecord], None]] = []
		self.on_changed: list[Callable[[], None]] = []

	# ------------------------------------------------------------------
	# 监听广播（异常隔离、不等待）
	# ------------------------------------------------------------------
	def _fire_done(self, rec: JobRecord) -> None:
		for fn in list(self.on_done):
			try:
				fn(rec)
			except Exception:  # noqa: BLE001
				_logger.debug("job on_done listener failed", exc_info=True)

	def _fire_changed(self) -> None:
		for fn in list(self.on_changed):
			try:
				fn()
			except Exception:  # noqa: BLE001
				_logger.debug("job on_changed listener failed", exc_info=True)

	# ------------------------------------------------------------------
	# start（生产方执行前预检容量；不排队、不抢占）
	# ------------------------------------------------------------------
	def _register(
		self, *, kind: str, label: str, owner_session_id: str
	) -> tuple[str | None, str]:
		owner = (owner_session_id or "").strip()
		if not owner:
			return None, "background job requires a session context"
		label = (label or "").strip()[:120] or kind
		with self._lock:
			running = sum(
				1
				for j in self._jobs.values()
				if j.owner_session_id == owner
				and j.status in (STATUS_RUNNING, STATUS_STOPPING)
			)
			if running >= MAX_CONCURRENT_JOBS_PER_OWNER:
				return None, (
					f"background job capacity full ({running}/{MAX_CONCURRENT_JOBS_PER_OWNER}) "
					f"for this session; use job_kill to free slots, then retry"
				)
			self._counter += 1
			job_id = f"{kind}-{self._counter}"
			self._jobs[job_id] = JobRecord(
				job_id=job_id, kind=kind, label=label, owner_session_id=owner
			)
			self._rings[job_id] = _Ring()
			self._cursors[job_id] = 0
		return job_id, ""

	def _spawn(self, job_id: str, producer: ProducerFn) -> None:
		def _worker() -> None:
			status, detail = STATUS_FAILED, ""
			try:
				status, detail = producer(lambda chunk: self._push(job_id, chunk))
			except Exception as exc:  # noqa: BLE001 — 生产方异常隔离为 failed
				status, detail = STATUS_FAILED, str(exc)[:400]
			self.settle(job_id, status, detail)

		threading.Thread(target=_worker, name=f"xeyo-job-{job_id}", daemon=True).start()

	def start(
		self,
		*,
		kind: str,
		label: str,
		owner_session_id: str,
		producer: ProducerFn,
		loop: asyncio.AbstractEventLoop | None = None,
	) -> tuple[str | None, str]:
		"""登记并启动后台任务。返回 (job_id, "") 或 (None, 教科书式错误)。"""
		job_id, err = self._register(
			kind=kind, label=label, owner_session_id=owner_session_id
		)
		if job_id is None:
			return None, err
		if loop is not None:
			self._loops[owner_session_id] = loop
		self._fire_changed()
		_logger.info("job started %s (%s: %s) owner=%s", job_id, kind, label, owner_session_id)
		self._spawn(job_id, producer)
		return job_id, ""

	def start_bash(
		self,
		*,
		command: str,
		cwd: str,
		label: str,
		owner_session_id: str,
		loop: asyncio.AbstractEventLoop | None = None,
	) -> tuple[str | None, str]:
		"""Bash 生产方：独立本地 abort（kill 走 job_kill；会话 abort 不杀 job）。"""
		from engine.abort import AbortController

		job_id, err = self._register(
			kind="bash", label=label, owner_session_id=owner_session_id
		)
		if job_id is None:
			return None, err
		ctl = AbortController()
		with self._lock:
			self._aborts[job_id] = ctl
		if loop is not None:
			self._loops[owner_session_id] = loop

		def _produce(push: PushFn) -> tuple[str, str]:
			from tools.bash_tool.runner import run_command

			result = run_command(
				command,
				cwd=cwd,
				timeout_ms=JOB_NO_TIMEOUT_MS,
				abort=ctl,
				on_output=push,
			)
			if result.interrupted:
				return STATUS_KILLED, "killed by job_kill"
			if result.timed_out:
				return STATUS_FAILED, "timed out"
			if result.code == 0:
				return STATUS_SUCCEEDED, ""
			return STATUS_FAILED, f"exit code {result.code}"

		self._fire_changed()
		_logger.info(
			"job started %s (bash: %s) owner=%s", job_id, label, owner_session_id
		)
		self._spawn(job_id, _produce)
		return job_id, ""

	def adopt_bash(
		self,
		*,
		handle: Any,
		command: str,
		cwd: str,
		label: str,
		owner_session_id: str,
		loop: asyncio.AbstractEventLoop | None = None,
	) -> tuple[str | None, str]:
		"""收编一个前台运行中的活进程为 bash job（前台超时自动晋升通道）。

		- handle 是 ``tools.bash_tool.runner.StreamHandle``（活进程 + 泵线程）；
		  已缓冲输出 replay 进 ring，后续增量经 attach 的 sink 持续推送。
		- abort 换绑：会话 abort 槽清空，本 job 的 ctl 接管（job_kill 可杀；
		  会话 abort 不杀 job——42 号冻结口径）。
		- 不适用超时（后台语义）；晋升只此一次，job 不再晋升。
		"""
		from engine.abort import AbortController

		job_id, err = self._register(
			kind="bash", label=label, owner_session_id=owner_session_id
		)
		if job_id is None:
			return None, err
		ctl = AbortController()
		with self._lock:
			self._aborts[job_id] = ctl
		# 同步换绑（在 spawn worker 前）：此刻起 job_kill 通道生效、
		# 会话 abort 不再杀进程（42 号冻结口径），无 detach/attach 竞态窗。
		try:
			handle.attach_abort(ctl)
		except Exception:  # noqa: BLE001 — handle 异常时按失败收编
			return None, "cannot adopt handle"
		if loop is not None:
			self._loops[owner_session_id] = loop

		def _produce(push: PushFn) -> tuple[str, str]:
			proc = getattr(handle, "proc", None)
			if proc is None:
				return STATUS_FAILED, "promoted handle has no process"
			try:
				while proc.poll() is None:
					time.sleep(0.2)
			finally:
				handle.release()  # 等泵收尾 + 关 Job Object（幂等）
			if handle.killed_by_abort:
				return STATUS_KILLED, "killed by job_kill"
			code = proc.returncode if proc.returncode is not None else 1
			if code == 0:
				return STATUS_SUCCEEDED, ""
			return STATUS_FAILED, f"exit code {code}"

		# 已缓冲输出先入 ring（replay_and_attach 同时挂上后续增量 sink）。
		try:
			prefill = handle.replay_and_attach(lambda chunk: self._push(job_id, chunk))
		except Exception:  # noqa: BLE001 — handle 异常时按失败收编
			return None, "cannot adopt handle"
		if prefill:
			self._push(job_id, prefill)
		self._fire_changed()
		_logger.info(
			"job adopted %s (bash: %s) owner=%s", job_id, label, owner_session_id
		)
		self._spawn(job_id, _produce)
		return job_id, ""

	# ------------------------------------------------------------------
	# 输出 / 快照
	# ------------------------------------------------------------------
	def _push(self, job_id: str, chunk: str) -> None:
		with self._lock:
			ring = self._rings.get(job_id)
			if ring is not None:
				ring.push(chunk)

	def read(
		self, job_id: str, caller_session_id: str
	) -> tuple[str, int, str, bool] | None:
		"""增量读。返回 (text, new_cursor, status, truncated)；未知/越权 → None。

		终态任务读终止输出（幂等）并置 reported；运行任务消费唯一游标。
		"""
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None or rec.owner_session_id != (caller_session_id or "").strip():
				return None
			ring = self._rings[job_id]
			text, cur, truncated = ring.read(self._cursors.get(job_id, 0))
			self._cursors[job_id] = cur
			status = rec.status
			if status in _TERMINAL:
				rec.reported = True
		return text, cur, status, truncated

	def snapshot_list(self, session_id: str) -> list[dict[str, Any]]:
		"""owner 快照：活跃行（startedAt 升序）在前，终态行（finishedAt 降序）在后。"""
		sid = (session_id or "").strip()
		with self._lock:
			mine = [j for j in self._jobs.values() if j.owner_session_id == sid]
		active = sorted(
			(j for j in mine if j.status in (STATUS_RUNNING, STATUS_STOPPING)),
			key=lambda j: (j.started_at, j.job_id),
		)
		done = sorted(
			(j for j in mine if j.status in _TERMINAL),
			key=lambda j: (-j.finished_at, j.job_id),
		)
		return [j.to_dict() for j in active + done]

	def version(self) -> int:
		with self._lock:
			return self._counter

	def _settle(self, job_id: str, status: str, detail: str) -> None:
		"""首次结果优先：终态单向门；随后 广播 → 通知决策。"""
		sid = ""
		fired_done: JobRecord | None = None
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None or rec.status in _TERMINAL:
				return
			rec.status = status if status in _TERMINAL else STATUS_FAILED
			rec.detail = (detail or "").strip()[:400]
			rec.finished_at = time.time()
			sid = rec.owner_session_id
			fired_done = rec
		if fired_done is not None:
			self._fire_done(fired_done)
		self._fire_changed()
		_logger.info(
			"job settled %s [%s] %s", job_id, status, (detail or "").strip()[:200]
		)
		self._queue_delivery_decision(sid)

	# 公开结算入口（测试 / 生产方直调）。
	def settle(self, job_id: str, status: str, detail: str = "") -> None:
		self._settle(job_id, status, detail)

	# ------------------------------------------------------------------
	# kill（终止）
	# ------------------------------------------------------------------
	def kill(self, job_id: str, caller_session_id: str, reason: str = "") -> str:
		"""请求取消：置 stopping + 标记已报告；取消异常由生产方隔离为 killed。"""
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None or rec.owner_session_id != (caller_session_id or "").strip():
				return f"unknown job: {job_id}"
			if rec.status in _TERMINAL:
				return f"job {job_id} already {rec.status}"
			rec.status = STATUS_STOPPING
			rec.reported = True
			rec.detail = (reason or "").strip()[:400]
			ctl = self._aborts.get(job_id)
		if ctl is not None:
			try:
				ctl.abort()
			except Exception:  # noqa: BLE001 — 取消异常 → 任务保持 running/stopping
				_logger.debug("job kill abort failed %s", job_id, exc_info=True)
		self._fire_changed()
		return f"requested cancellation of job {job_id}"

	# ------------------------------------------------------------------
	# 通知决策（§6）：忙→挂起；闲+预算→唤醒轮；预算尽→pending 等人类
	# ------------------------------------------------------------------
	def _queue_delivery_decision(self, sid: str) -> None:
		"""settle（可能在 worker 线程）→ 代理到启动时的 loop 上做异步决策。"""
		loop = self._loops.get(sid)
		if loop is None or loop.is_closed():
			# 无 loop（CLI in-process）：不主动唤醒；等 hub / 人类下一轮补投。
			return
		try:
			loop.call_soon_threadsafe(self._schedule_delivery_task, sid)
		except RuntimeError:
			pass

	def _schedule_delivery_task(self, sid: str) -> None:
		with self._lock:
			existing = self._wake_tasks.get(sid)
		if existing is not None and not existing.done():
			return  # 决策已在途（防抖去重；新结算由在途 tick 覆盖）
		try:
			task = asyncio.create_task(self.on_delivery_tick(sid))
		except RuntimeError:
			return
		with self._lock:
			self._wake_tasks[sid] = task

	async def on_delivery_tick(self, sid: str) -> None:
		"""决策点：owner 忙 → 挂起；闲 + 预算 → 唤醒；预算尽 → pending。"""
		try:
			await asyncio.sleep(_WAKE_DEBOUNCE_S)
			if _turn_running(sid):
				return
			ids = self._unreported_terminal(sid)
			if not ids and not self._pending.get(sid):
				return
			# 归并：未报告终态 + 既有 pending 一次性合并投递。
			merged = self._merge_pending(sid, ids)
			if not merged:
				return
			if not self.consume_wake(sid):
				# 预算尽：通知留在 pending，等人类下一轮 T_now 补投（§6.3）。
				self._requeue(sid, merged)
				return
			digest = self._build_digest(sid, merged)
			if not digest:
				return
			from server.synthetic_round import submit_synthetic

			ok = await submit_synthetic(sid, digest, surface="job-wake")
			if not ok:
				# 轮没开起来（env 缺失 / 409 竞争）：退回 pending（不退预算，
				# 防止与 goal 轮互激 thrash；人类下一轮 T_now 兜底）。
				self._requeue(sid, merged)
		except Exception:  # noqa: BLE001
			_logger.debug("job delivery decision failed sid=%s", sid, exc_info=True)
		finally:
			with self._lock:
				if self._wake_tasks.get(sid) is asyncio.current_task():
					self._wake_tasks.pop(sid, None)

	def _unreported_terminal(self, sid: str) -> list[str]:
		with self._lock:
			return [
				j.job_id
				for j in self._jobs.values()
				if j.owner_session_id == sid
				and j.status in _TERMINAL
				and not j.reported
			]

	def _merge_pending(self, sid: str, ids: list[str]) -> list[str]:
		with self._lock:
			existing = self._pending.setdefault(sid, [])
			merged = list(dict.fromkeys(existing + ids))
			existing.clear()
			return merged

	def _requeue(self, sid: str, ids: list[str]) -> None:
		with self._lock:
			pend = self._pending.setdefault(sid, [])
			for jid in ids:
				if jid not in pend:
					pend.append(jid)
					rec = self._jobs.get(jid)
					if rec is not None:
						rec.reported = False
			self._wake_budget[sid] = max(0, self._wake_budget.get(sid, 0))

	def _build_digest(self, sid: str, ids: list[str]) -> str:
		with self._lock:
			rows = []
			for jid in ids:
				rec = self._jobs.get(jid)
				if rec is None:
					continue
				rec.reported = True  # 消费即置位（§6.4 抑制重复）
				rows.append(
					f"background job {rec.job_id} ({rec.kind}: {rec.label}) "
					f"finished [status: {rec.status}]."
					+ (f" Detail: {rec.detail}." if rec.detail else "")
				)
		if not rows:
			return ""
		body = "\n".join(rows)
		return (
			"[Background jobs] The following background jobs finished. "
			"Read their output with job_output, then continue or wrap up. "
			"This is a completion notification, not a new task.\n" + body
		)

	# hub 在 turn settlement 时调用：把 turn 期间挂起的 pending 并入决策。
	async def on_turn_settled(
		self, session_id: str, final_status: str, stop_reason: str
	) -> None:
		try:
			_ = final_status, stop_reason
			if _turn_running(session_id):
				return
			await self.on_delivery_tick(session_id)
		except Exception:  # noqa: BLE001
			_logger.debug("job on_turn_settled failed sid=%s", session_id, exc_info=True)

	# ------------------------------------------------------------------
	# 共享唤醒预算（§3.4）与让位
	# ------------------------------------------------------------------
	def consume_wake(self, session_id: str) -> bool:
		with self._lock:
			left = self._wake_budget.get(
				session_id, MAX_CONSECUTIVE_WAKES
			)
			if left <= 0:
				return False
			self._wake_budget[session_id] = left - 1
			return True

	def restore_wake(self, session_id: str) -> None:
		"""只有人类输入恢复预算（41 号 chat.py 入口调用）。"""
		with self._lock:
			self._wake_budget[session_id] = MAX_CONSECUTIVE_WAKES

	def refund_wake(self, session_id: str) -> None:
		"""退还一次预算：合成轮 consume 后提交失败（turn 未启动）时回补。

		与 ``restore_wake`` 的区别：只 +1 且封顶（局部回补，不是人类输入的全量恢复）。
		"""
		with self._lock:
			cur = self._wake_budget.get(session_id, MAX_CONSECUTIVE_WAKES)
			self._wake_budget[session_id] = min(
				MAX_CONSECUTIVE_WAKES, int(cur) + 1
			)

	def wake_budget_left(self, session_id: str) -> int:
		with self._lock:
			return self._wake_budget.get(session_id, MAX_CONSECUTIVE_WAKES)

	def cancel_wake(self, session_id: str) -> None:
		"""人类消息让位（§3.3）：取消在途唤醒任务；pending 保留（不消耗预算）。"""
		with self._lock:
			task = self._wake_tasks.pop(session_id, None)
		if task is not None and not task.done():
			task.cancel()

	def pending_digest(self, session_id: str) -> str:
		"""人类下一轮 T_now 补投：摘出 pending（一次性消费）并置 reported。"""
		sid = (session_id or "").strip()
		with self._lock:
			ids = self._pending.pop(sid, [])
			if not ids:
				return ""
			rows = []
			for jid in ids:
				rec = self._jobs.get(jid)
				if rec is None:
					continue
				rec.reported = True
				rows.append(
					f"- {rec.job_id} [{rec.kind}] {rec.status}"
					+ (f" — {rec.detail}" if rec.detail else "")
					+ f" — {rec.label}"
				)
		if not rows:
			return ""
		return "\n".join(rows)

	def shutdown(self) -> None:
		with self._lock:
			tasks = list(self._wake_tasks.values())
			self._wake_tasks.clear()
		for t in tasks:
			if not t.done():
				t.cancel()


_registry: JobRegistry | None = None


def get_job_registry() -> JobRegistry:
	global _registry
	if _registry is None:
		_registry = JobRegistry()
	return _registry
