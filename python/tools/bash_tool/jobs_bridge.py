"""Bash → JobRegistry 桥（42 号 P0）。

依赖方向约束：``tools/`` 不 import ``server/``（CLI in-process 运行时无 server）。
桥在**调用时**惰性尝试 server.registry；不可用返回 None，BashTool 落回旧式
日志文件后台——server 场景获得 42 号 job 语义（完成通知 / job_output / kill），
纯引擎场景行为逐字节不变。
"""

from __future__ import annotations

import asyncio


def start_registry_job(
	*,
	command: str,
	cwd: str,
	description: str | None,
	session_id: str,
	loop: asyncio.AbstractEventLoop | None = None,
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
	try:
		from server.job_registry import get_job_registry
	except Exception:  # noqa: BLE001 — 无 server 运行时（CLI in-process）
		return None
	try:
		first_line = command.strip().splitlines()[0] if command.strip() else ""
		label = (description or first_line).strip()[:120]
		job_id, err = get_job_registry().start_bash(
			command=command,
			cwd=cwd,
			label=label,
			owner_session_id=sid,
			loop=loop,
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
) -> tuple[str, str] | None:
	"""前台超时晋升：把运行中的活进程收编为 42 号 job。

	返回语义同 ``start_registry_job``：None=registry 不可用（调用方回退
	旧式日志后台或继续前台等待）；("", err)=拒绝；(job_id, "")=成功。
	"""
	sid = (session_id or "").strip()
	if not sid:
		return None
	try:
		from server.job_registry import get_job_registry
	except Exception:  # noqa: BLE001 — 无 server 运行时（CLI in-process）
		return None
	try:
		first_line = command.strip().splitlines()[0] if command.strip() else ""
		label = (description or first_line).strip()[:120]
		job_id, err = get_job_registry().adopt_bash(
			handle=handle,
			command=command,
			cwd=cwd,
			label=label,
			owner_session_id=sid,
			loop=loop,
		)
		if job_id is None:
			return ("", err)
		return (job_id, "")
	except Exception:  # noqa: BLE001
		return None
