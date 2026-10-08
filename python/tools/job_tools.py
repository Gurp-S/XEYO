"""后台任务三工具（42 号 P0）——``job_output`` / ``job_list`` / ``job_kill``。

后台任务语义：**恒注册**（无任务时空转），schema 不随状态抖动；
``job_output``/``job_list`` 只读，``job_kill`` 仅限本会话自建任务（owner 即
安全边界），默认 allow + 日志（冻结口径 7）。

- ``job_output``：单游标增量消费（registry 持有唯一游标）；``wait=true`` 阻塞
	至终态或超时；server registry / Docker 后台表均由完成事件唤醒；响应以
	``[status: ...]`` 收尾。
- ``job_list``：owner 快照一行一任务；空会话返回 ``(no background jobs)``。
- ``job_kill``：请求取消（stopping → killed）；终态任务返回幂等提示。
- registry 不可用（无 server 运行时）全部降级为空态文案，不报错。
"""

from __future__ import annotations

import asyncio
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.error_taxonomy import INVALID_ARGUMENT, NOT_FOUND, TRANSIENT_INFRA

JOB_OUTPUT_TOOL_NAME = "job_output"
JOB_LIST_TOOL_NAME = "job_list"
JOB_KILL_TOOL_NAME = "job_kill"

_OUTPUT_WAIT_DEFAULT_MS = 30_000
_OUTPUT_WAIT_MAX_MS = 600_000


def _coerce_bool(value: Any, default: bool = False) -> bool:
	"""与 Bash/Edit/Grep/TodoWrite 同一条字面量口径（2026-10-05）。

	`wait` 在 schema 里是 boolean，模型常写成字符串；裸 ``bool("false")`` 是 True
	⇒ ``job_output`` 会做与要求相反的事并按住回合到超时。认不出的值回默认。
	"""
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	if isinstance(value, str):
		s = value.strip().lower()
		if s in ("true", "on", "1", "yes"):
			return True
		if s in ("false", "off", "0", "no"):
			return False
	return default


def _registry() -> Any:
	from server.job_registry import get_job_registry

	return get_job_registry()


def _session_id() -> str:
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		if ctx is not None and ctx.session_id:
			return str(ctx.session_id).strip()
	except Exception:  # noqa: BLE001
		pass
	return ""


def _owner_only(session_id: str) -> str:
	return session_id or _session_id()


def _format_status_line(status: str) -> str:
	return f"[status: {status}]"


def _clip(text: str, limit: int) -> str:
	text = text or ""
	return text if len(text) <= limit else text[:limit] + "…"


class JobOutputTool:
	name = JOB_OUTPUT_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": (
				"Read a background job's output (incremental cursor; safe to "
				"call again while running). wait=true blocks until it finishes "
				"or the timeout. Ends with [status: ...]."
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"job_id": {"type": "string", "description": "Job id from start"},
					"wait": {
						"type": "boolean",
						"description": "Block until terminal or timeout (default false)",
					},
					"timeout_ms": {
						"type": "number",
						"description": "Max wait in ms when wait=true (default 30000, cap 600000)",
					},
				},
				"required": ["job_id"],
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		job_id = str(input.get("job_id") or "").strip()
		if not job_id:
			return ToolResult(
				content="job_id is required",
				is_error=True,
				status="error",
				error_kind=INVALID_ARGUMENT,
				retryable=False,
			)
		# server registry 与 Docker 直连后台表都支持事件唤醒；不再按容器
		# 路由强制关闭 wait=true。ContextVar 仍只用于选择哪条后台事实源。
		wait = _coerce_bool(input.get("wait"), False)
		try:
			timeout_ms = int(float(input.get("timeout_ms") or _OUTPUT_WAIT_DEFAULT_MS))
		except (TypeError, ValueError, OverflowError):
			timeout_ms = _OUTPUT_WAIT_DEFAULT_MS
		timeout_ms = max(1_000, min(_OUTPUT_WAIT_MAX_MS, timeout_ms))
		# docker 后台 job 回退（评测 headless：registry 依赖 server，不可用）
		try:
			from tools.bash_tool.bash_tool import docker_bg_snapshot
			from tools.bash_tool.bash_tool import wait_docker_bg_change

			bg = {j["job_id"]: j for j in docker_bg_snapshot()}
			if job_id in bg:
				j = bg[job_id]
				deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
				while wait and j["status"] == "running":
					if abort.aborted or asyncio.get_running_loop().time() >= deadline:
						break
					remaining = deadline - asyncio.get_running_loop().time()
					await wait_docker_bg_change(job_id, remaining, abort)
					if abort.aborted:
						break
					bg = {x["job_id"]: x for x in docker_bg_snapshot()}
					j = bg.get(job_id, j)
				text = (j.get("output") or "").strip()
				parts: list[str] = []
				if text:
					parts.append(text[-8000:])
				elif j["status"] == "running":
					parts.append("(no output yet)")
				parts.append(_format_status_line(j["status"]))
				from engine.execution_facts import enabled as fact_contracts
				if fact_contracts():
					parts.append(f"[activity: started_at={j.get('started', 0):.3f}; last_output_at={j.get('last_output_at', 0):.3f}; output_chars={j.get('output_chars', len(text))}; finished_at={j.get('finished_at', 0):.3f}]")
				return ToolResult(
					content="\n".join(parts),
					status="running" if j["status"] == "running" else "ok",
				)
		except Exception:  # noqa: BLE001
			pass
		try:
			reg = _registry()
			sid = _owner_only(_session_id())
			# 先拿变更序号再读：若生产线程在 read 后、注册 waiter 前
			# 写入输出，wait_for_change 会用序号补上这个窗口，避免丢唤醒。
			token = reg.change_token(job_id, sid)
			res = reg.read(job_id, sid)
			if res is None:
				return ToolResult(
					content=f"unknown job: {job_id}",
					is_error=True,
					status="error",
					error_kind=NOT_FOUND,
					retryable=False,
				)
			text, _cursor, status, truncated = res
			# read() 是按 (job, 单游标) 增量消费：循环里每读一次游标就前移。必须累加，
			# 否则当输出在"运行中"的某次读里被消费、而 settle 触发的最后一次读到空增量时，
			# 覆写 text 会把先前块丢掉（表现为 status=succeeded 却没有输出行）。
			chunks: list[str] = [text or ""]
			truncated_any = truncated
			deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
			while wait and status == "running":
				if abort.aborted:
					break
				remaining = deadline - asyncio.get_running_loop().time()
				if remaining <= 0 or token is None:
					break
				token = await reg.wait_for_change(
					job_id, sid, token, timeout_s=remaining
				)
				if token is None:
					break
				res = reg.read(job_id, sid)
				if res is None:
					break
				text, _cursor, status, truncated = res
				chunks.append(text or "")
				truncated_any = truncated_any or truncated
			accumulated = "".join(chunks)
			parts: list[str] = []
			if truncated_any:
				parts.append("(earlier output truncated)")
			if accumulated.strip():
				parts.append(accumulated.rstrip())
			elif status == "running":
				parts.append("(no new output)")
			parts.append(_format_status_line(status))
			from engine.execution_facts import enabled as fact_contracts
			if fact_contracts():
				job = next((j for j in reg.snapshot_list(sid) if j["job_id"] == job_id), None)
				if job:
					parts.append(f"[activity: started_at={job['started_at']:.3f}; last_output_at={job['last_output_at']:.3f}; output_chars={job['output_chars']}; finished_at={job['finished_at']:.3f}]")
			return ToolResult(
				content="\n".join(parts),
				status="running" if status == "running" else "ok",
			)
		except Exception:  # noqa: BLE001 — registry 不可用降级空态
			return ToolResult(
				content=f"(no background jobs)\n{_format_status_line('unknown')}",
				is_error=True,
				status="error",
				error_kind=TRANSIENT_INFRA,
				retryable=True,
			)


class JobListTool:
	name = JOB_LIST_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": (
				"List this session's background jobs (running first, then "
				"finished)."
			),
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		_ = input, abort
		# docker 后台 job 回退（评测 headless）
		try:
			from tools.bash_tool.bash_tool import docker_bg_snapshot

			bg = docker_bg_snapshot()
			if bg:
				lines = [
					f"{j['job_id']} [docker] {j['status']}"
					f" — {_clip(str(j.get('command') or ''), 80)}"
					for j in bg
				]
				return ToolResult(content="\n".join(lines))
		except Exception:  # noqa: BLE001
			pass
		try:
			jobs = _registry().snapshot_list(_owner_only(_session_id()))
		except Exception:  # noqa: BLE001
			jobs = []
		if not jobs:
			return ToolResult(content="(no background jobs)")
		lines = []
		for j in jobs:
			row = (
				f"{j.get('job_id')} [{j.get('kind')}] {j.get('status')}"
				f" — {_clip(str(j.get('label') or ''), 80)}"
			)
			detail = _clip(str(j.get("detail") or ""), 120)
			if detail:
				row += f" ({detail})"
			lines.append(row)
		return ToolResult(content="\n".join(lines))


class JobKillTool:
	name = JOB_KILL_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": (
				"Request cancellation of one of this session's background jobs."
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"job_id": {"type": "string", "description": "Job id to stop"},
					"reason": {
						"type": "string",
						"description": "Optional short reason",
					},
				},
				"required": ["job_id"],
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		job_id = str(input.get("job_id") or "").strip()
		if not job_id:
			return ToolResult(
				content="job_id is required",
				is_error=True,
				status="error",
				error_kind=INVALID_ARGUMENT,
				retryable=False,
			)
		reason = str(input.get("reason") or "").strip()
		# 容器后台 job 优先（与 job_output/job_list 同一可见面，2026-09-16 对齐）：
		# 此前 kill 只查 registry ⇒ 模型能看见容器 job 却杀不掉，每次白烧一轮。
		try:
			from tools.bash_tool.bash_tool import cancel_docker_bg, docker_bg_snapshot

			if any(j["job_id"] == job_id for j in docker_bg_snapshot()):
				msg = cancel_docker_bg(job_id, reason)
				if msg is None:
					return ToolResult(
						content=f"unknown job: {job_id}",
						is_error=True,
						status="error",
						error_kind=NOT_FOUND,
						retryable=False,
					)
				return ToolResult(content=msg)
		except Exception:  # noqa: BLE001 — 回退 registry 路径
			pass
		try:
			msg = _registry().kill(job_id, _owner_only(_session_id()), reason)
			unknown = msg.startswith("unknown job")
			return ToolResult(
				content=msg,
				is_error=unknown,
				status="error" if unknown else "ok",
				error_kind=NOT_FOUND if unknown else None,
				retryable=False,
			)
		except Exception:  # noqa: BLE001
			return ToolResult(
				content=f"unknown job: {job_id}",
				is_error=True,
				status="error",
				error_kind=NOT_FOUND,
				retryable=False,
			)
