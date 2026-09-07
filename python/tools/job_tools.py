"""后台任务三工具（42 号 P0）——``job_output`` / ``job_list`` / ``job_kill``。

后台任务语义：**恒注册**（无任务时空转），schema 不随状态抖动；
``job_output``/``job_list`` 只读，``job_kill`` 仅限本会话自建任务（owner 即
安全边界），默认 allow + 日志（冻结口径 7）。

- ``job_output``：单游标增量消费（registry 持有唯一游标）；``wait=true`` 阻塞
  至终态或超时；响应以 ``[status: ...]`` 收尾。
- ``job_list``：owner 快照一行一任务；空会话返回 ``(no background jobs)``。
- ``job_kill``：请求取消（stopping → killed）；终态任务返回幂等提示。
- registry 不可用（无 server 运行时）全部降级为空态文案，不报错。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.container_routing import current_container as _routed_container

JOB_OUTPUT_TOOL_NAME = "job_output"
JOB_LIST_TOOL_NAME = "job_list"
JOB_KILL_TOOL_NAME = "job_kill"

_OUTPUT_WAIT_DEFAULT_MS = 30_000
_OUTPUT_WAIT_MAX_MS = 600_000
_POLL_INTERVAL_S = 0.25


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
			return ToolResult(content="job_id is required", is_error=True)
		# docker 评测路由下禁用阻塞等待：同步工具调用期间模型无法做任何其他
		# 工作，wait 最多烧 60s×N 次（实测 gpt2/pipeline 的 p90 间隔黑洞）。
		# 完成通知由 pending_jobs_block 每回合自动镜像——模型根本不需要 wait。
		# 并发 trial 防串线：ContextVar 优先于进程级 env（同 bash_tool）。
		if _routed_container() or os.environ.get("XEYO_DOCKER_CONTAINER", "").strip():
			wait = False
		else:
			wait = bool(input.get("wait"))
		try:
			timeout_ms = int(float(input.get("timeout_ms") or _OUTPUT_WAIT_DEFAULT_MS))
		except (TypeError, ValueError):
			timeout_ms = _OUTPUT_WAIT_DEFAULT_MS
		timeout_ms = max(1_000, min(_OUTPUT_WAIT_MAX_MS, timeout_ms))
		# docker 后台 job 回退（评测 headless：registry 依赖 server，不可用）
		try:
			from tools.bash_tool.bash_tool import docker_bg_snapshot

			bg = {j["job_id"]: j for j in docker_bg_snapshot()}
			if job_id in bg:
				j = bg[job_id]
				deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
				while wait and j["status"] == "running":
					if abort.aborted or asyncio.get_running_loop().time() >= deadline:
						break
					await asyncio.sleep(_POLL_INTERVAL_S)
					bg = {x["job_id"]: x for x in docker_bg_snapshot()}
					j = bg.get(job_id, j)
				text = (j.get("output") or "").strip()
				parts: list[str] = []
				if text:
					parts.append(text[-8000:])
				elif j["status"] == "running":
					parts.append("(no output yet)")
				parts.append(_format_status_line(j["status"]))
				return ToolResult(content="\n".join(parts))
		except Exception:  # noqa: BLE001
			pass
		try:
			reg = _registry()
			sid = _owner_only(_session_id())
			res = reg.read(job_id, sid)
			if res is None:
				return ToolResult(content=f"unknown job: {job_id}", is_error=True)
			text, _cursor, status, truncated = res
			deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
			while wait and status == "running":
				if abort.aborted:
					break
				if asyncio.get_running_loop().time() >= deadline:
					break
				await asyncio.sleep(_POLL_INTERVAL_S)
				res = reg.read(job_id, sid)
				if res is None:
					break
				text, _cursor, status, truncated = res
			parts: list[str] = []
			if truncated:
				parts.append("(earlier output truncated)")
			if (text or "").strip():
				parts.append(text.rstrip())
			elif status == "running":
				parts.append("(no new output)")
			parts.append(_format_status_line(status))
			return ToolResult(content="\n".join(parts))
		except Exception:  # noqa: BLE001 — registry 不可用降级空态
			return ToolResult(content=f"(no background jobs)\n{_format_status_line('unknown')}")


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
			return ToolResult(content="job_id is required", is_error=True)
		reason = str(input.get("reason") or "").strip()
		try:
			msg = _registry().kill(job_id, _owner_only(_session_id()), reason)
			unknown = msg.startswith("unknown job")
			return ToolResult(content=msg, is_error=unknown)
		except Exception:  # noqa: BLE001
			return ToolResult(content=f"unknown job: {job_id}", is_error=True)
