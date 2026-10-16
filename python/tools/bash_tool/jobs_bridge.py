"""Bash background start/adoption through an explicitly supplied host port.

An absent or failing host preserves the existing log-file fallback.
"""

from __future__ import annotations

import asyncio
from typing import Any
from collections.abc import Callable
from tools.host_services import BackgroundJobs


def start_registry_job(
	*,
	command: str,
	cwd: str,
	description: str | None,
	session_id: str,
	loop: asyncio.AbstractEventLoop | None = None,
	parent_abort: Any | None = None,
	jobs: Callable[[], BackgroundJobs] | None = None,
) -> tuple[str, str] | None:
	"""尝试把命令登记为 42 号后台 job。

	返回：
	- ``None`` —— registry 不可用（无 server / 异常）→ 调用方走旧式后台；
	- ``("", error)`` —— registry 拒绝（容量满 / 无会话上下文）→ 教科书式错误；
	- ``(job_id, "")`` —— 成功。
	"""
	sid = (session_id or "").strip()
	if not sid:
		return None
	if jobs is None:
		return None
	try:
		registry = jobs()
		first_line = command.strip().splitlines()[0] if command.strip() else ""
		label = (description or first_line).strip()[:120]
		if parent_abort is None:
			from engine.cancellation import get_session_scope

			parent_abort = get_session_scope(sid)
		job_id, err = registry.start_bash(
			command=command,
			cwd=cwd,
			label=label,
			owner_session_id=sid,
			loop=loop,
			parent_abort=parent_abort,
		)
		if job_id is None:
			return ("", err)
		return (job_id, "")
	except Exception:  # noqa: BLE001
		return None


def adopt_registry_job(
	*,
	handle: Any,
	command: str,
	cwd: str,
	description: str | None,
	session_id: str,
	loop: asyncio.AbstractEventLoop | None = None,
	parent_abort: Any | None = None,
	jobs: Callable[[], BackgroundJobs] | None = None,
) -> tuple[str, str] | None:
	"""前台超时晋升：把运行中的活进程收编为 42 号 job。

	返回语义同 ``start_registry_job``：None=registry 不可用（调用方回退
	旧式日志后台或继续前台等待）；("", err)=拒绝；(job_id, "")=成功。
	"""
	sid = (session_id or "").strip()
	if not sid:
		return None
	if jobs is None:
		return None
	try:
		registry = jobs()
		first_line = command.strip().splitlines()[0] if command.strip() else ""
		label = (description or first_line).strip()[:120]
		if parent_abort is None:
			from engine.cancellation import get_session_scope

			parent_abort = get_session_scope(sid)
		job_id, err = registry.adopt_bash(
			handle=handle,
			command=command,
			cwd=cwd,
			label=label,
			owner_session_id=sid,
			loop=loop,
			parent_abort=parent_abort,
		)
		if job_id is None:
			return ("", err)
		return (job_id, "")
	except Exception:  # noqa: BLE001
		return None
