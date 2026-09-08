from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from engine.abort import AbortController
from tools.bash_tool.destructive_guard import settle_destructive_plan
from tools.bash_tool.runner import run_command

if TYPE_CHECKING:  # 循环导入防护：仅类型标注用
	from tools.bash_tool.runner import StreamHandle

# task_id → 可取消的局部 abort（与会话 abort 合并轮询）
_TASK_ABORTS: dict[str, AbortController] = {}
_TASK_LOCK = threading.Lock()


@dataclass
class BackgroundHandle:
	task_id: str
	log_path: str


class _MergedAbort(AbortController):
	"""task 本地 abort 或父 abort 任一触发即视为已中止。"""

	def __init__(
		self, local: AbortController, parent: AbortController | None
	) -> None:
		super().__init__()
		self._local = local
		self._parent = parent

	@property
	def aborted(self) -> bool:
		if self._local.aborted:
			return True
		if self._parent is not None and self._parent.aborted:
			return True
		return self._aborted


def cancel_background(task_id: str) -> bool:
	"""取消后台 Bash 任务；未知 id 返回 False。"""
	with _TASK_LOCK:
		ctl = _TASK_ABORTS.get(task_id)
	if ctl is None:
		return False
	ctl.abort()
	return True


def start_background(
	command: str,
	*,
	cwd: str,
	timeout_ms: int,
	description: str | None = None,
	abort: AbortController | None = None,
	guard_plan: Any = None,
) -> BackgroundHandle:
	"""
	立即返回 task_id；daemon 线程实时把输出追加进 log（模型可随时 Read）。
	绑定会话 abort + 可 cancel_background(task_id) 杀进程。
	guard_plan 非 None 时（#14 Phase A 破坏性命令 before 快照）在 worker
	结束的 finally 里结算（run_command 返回即视为执行过 → completed）。
	"""
	task_id = uuid.uuid4().hex[:12]
	task_abort = AbortController()
	with _TASK_LOCK:
		_TASK_ABORTS[task_id] = task_abort

	log_dir = os.path.join(cwd, ".xeyo", "bash-bg")
	os.makedirs(log_dir, exist_ok=True)
	_cleanup_old_logs(log_dir)
	log_path = os.path.join(log_dir, f"{task_id}.log")

	with open(log_path, "w", encoding="utf-8") as f:
		f.write(f"# bash background task {task_id}\n")
		if description:
			f.write(f"# description: {description}\n")
		f.write(f"# command: {command}\n")
		f.write("# status: running\n\n")

	merged = _MergedAbort(task_abort, abort)

	def _worker() -> None:
		log = open(log_path, "a", encoding="utf-8", errors="replace")
		try:
			result = run_command(
				command,
				cwd=cwd,
				timeout_ms=timeout_ms,
				abort=merged,
				# 逐行实时落盘：不再等任务结束才写（运行期 Read 只见空文件），
				# 也不在父进程积压整个输出。
				on_output=lambda chunk: (
					log.write(chunk) or log.flush()
				),
			)
			with open(log_path, "a", encoding="utf-8", errors="replace") as f:
				if not (result.stdout or "").endswith("\n"):
					f.write("\n")
				if result.timed_out:
					f.write("# status: timed_out\n")
				elif result.interrupted:
					f.write("# status: interrupted\n")
				else:
					f.write(f"# status: completed exit={result.code}\n")
		finally:
			log.close()
			if guard_plan is not None:
				try:
					settle_destructive_plan(guard_plan, executed=True)
				except Exception:  # noqa: BLE001 — fail-open
					pass
			with _TASK_LOCK:
				_TASK_ABORTS.pop(task_id, None)

	threading.Thread(
		target=_worker, name=f"bash-bg-{task_id}", daemon=True
	).start()
	return BackgroundHandle(task_id=task_id, log_path=log_path)


def _append_log(log_path: str, chunk: str) -> None:
	if not chunk:
		return
	try:
		with open(log_path, "a", encoding="utf-8", errors="replace") as f:
			f.write(chunk)
			f.flush()
	except OSError:
		pass


def adopt_background(
	handle: "StreamHandle",
	*,
	cwd: str,
	description: str | None = None,
	parent_abort: AbortController | None = None,
	guard_plan: Any = None,
) -> BackgroundHandle:
	"""registry 不可用时的晋升回退：把前台活进程转成日志文件后台任务。

	已缓冲输出先落盘，随后增量实时追加（replay_and_attach 原子换 sink）；
	abort 换绑 merged(task local, parent)——cancel_background(task_id) 与
	会话 abort 均可杀。与 start_background 的产物形状一致（task_id + log）。
	guard_plan 非 None 时在 worker 结束的 finally 里结算。
	"""
	task_id = uuid.uuid4().hex[:12]
	task_abort = AbortController()
	with _TASK_LOCK:
		_TASK_ABORTS[task_id] = task_abort

	log_dir = os.path.join(cwd, ".xeyo", "bash-bg")
	os.makedirs(log_dir, exist_ok=True)
	_cleanup_old_logs(log_dir)
	log_path = os.path.join(log_dir, f"{task_id}.log")

	with open(log_path, "w", encoding="utf-8") as f:
		f.write(f"# bash background task {task_id} (promoted)\n")
		if description:
			f.write(f"# description: {description}\n")
		f.write("# status: running\n\n")

	prefill = handle.replay_and_attach(lambda chunk: _append_log(log_path, chunk))
	_append_log(log_path, prefill)

	merged = _MergedAbort(task_abort, parent_abort)
	handle.attach_abort(merged)

	def _worker() -> None:
		try:
			proc = handle.proc
			if proc is None:
				return
			try:
				while proc.poll() is None:
					time.sleep(0.2)
			finally:
				handle.release()
			if handle.killed_by_abort:
				status = "interrupted"
			else:
				code = proc.returncode if proc.returncode is not None else 1
				status = f"completed exit={code}"
			_append_log(log_path, f"\n# status: {status}\n")
		finally:
			if guard_plan is not None:
				try:
					settle_destructive_plan(guard_plan, executed=True)
				except Exception:  # noqa: BLE001 — fail-open
					pass
			with _TASK_LOCK:
				_TASK_ABORTS.pop(task_id, None)

	threading.Thread(
		target=_worker, name=f"bash-bg-{task_id}", daemon=True
	).start()
	return BackgroundHandle(task_id=task_id, log_path=log_path)


def _cleanup_old_logs(log_dir: str, *, ttl_s: float = 7 * 24 * 3600) -> None:
	"""删除超 TTL 的历史日志（.xeyo/bash-bg 曾无限累积）。"""
	import time

	now = time.time()
	try:
		for name in os.listdir(log_dir):
			if not name.endswith(".log"):
				continue
			p = os.path.join(log_dir, name)
			try:
				if now - os.path.getmtime(p) > ttl_s:
					os.unlink(p)
			except OSError:
				continue
	except OSError:
		pass
