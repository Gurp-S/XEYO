"""BashTool — Shell 执行器 (P0).

模型填参数 → validate → checkPermissions(stub) → call → semantics → truncate → map
"""

# TODO: [后台] 超时自动转后台、与 TaskOutput 打通
# TODO: [sed] _simulatedSedEdit 预览写盘
# TODO: [取消] 后台任务 abort/kill
# TODO: [测试] 语义 exit、截断、Windows 编码、复合命令

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

_log = logging.getLogger(__name__)

from engine.abort import AbortController
from permissions.filesystem import (
	PermissionDecision,
	expand_to_abs,
	path_in_allowed_working_path,
	permission_preapproved,
)
from permissions.policy import evaluate_policy
from tools.base_tool import ToolResult
from tools.bash_tool.background import start_background
from tools.bash_tool.cmd_compact import compact_command_output
from tools.bash_tool.jobs_bridge import adopt_registry_job, start_registry_job
from tools.bash_tool.prompt import BASH_TOOL_NAME, DESCRIPTION
from tools.bash_tool.runner import (
	finish_streaming,
	shell_display_name,
	spawn_streaming,
)
from tools.bash_tool.semantics import extract_base_command, interpret_command_result
from tools.bash_tool.truncate import truncate_for_model
from tools.bash_tool.precheck import precheck_command


def fast_fail_message(failure_reason: str) -> str:
	"""快速失败文案：给可行动的改法；不提不存在的"绕过旗标"，别诱导模型空转。"""
	return (
		"Command blocked by precheck (would hang waiting for a TTY/editor).\n"
		f"Reason: {failure_reason}\n"
		"Fix the command per the reason and retry; if it truly needs a human "
		"in a real terminal, tell the user to run it themselves."
	)

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000
MAX_RESULT_CHARS = 30_000
MAX_COMMAND_CHARS = 100_000
#: 前台命令运行超过该阈值仍未结束 → 自动晋升为后台 job（0=关闭）。
#: 进程不重启、已累积输出随晋升返回；env XEYO_BASH_PROMOTE_MS 可调。
BASH_PROMOTE_DEFAULT_MS = 45_000


def promote_threshold_ms() -> int:
	raw = os.environ.get("XEYO_BASH_PROMOTE_MS", "").strip()
	if not raw:
		return BASH_PROMOTE_DEFAULT_MS
	try:
		return max(0, int(raw))
	except ValueError:
		return BASH_PROMOTE_DEFAULT_MS
# Phase 2 工人 Bash：更短默认/上限，防测挂烧钱（可用 XEYO_WORKER_BASH_TIMEOUT_MS 覆盖默认）。
WORKER_BASH_DEFAULT_TIMEOUT_MS = 30_000
WORKER_BASH_MAX_TIMEOUT_MS = 60_000

SILENT_COMMANDS = frozenset({
	"mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown",
	"touch", "ln", "cd", "export", "unset", "wait",
})


def prompt() -> str:
	return DESCRIPTION.strip()


def expect_no_output(command: str) -> bool:
	base = extract_base_command(command)
	return base in SILENT_COMMANDS


def _worker_bash_active() -> bool:
	try:
		from permissions.write_scope import get_write_scope

		return get_write_scope() is not None
	except Exception:  # noqa: BLE001
		return False


def _coerce_bool(value: Any, default: bool = False) -> bool:
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


def _coerce_optional_int(value: Any) -> int | None:
	if value is None or value == "":
		return None
	# bool 是 int 的子类：模型误传 `true` 作 timeout 时按无效处理 → None（取默认），
	# 避免被解释成 1ms 导致命令立即超时。
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)
	if isinstance(value, str):
		try:
			return int(float(value.strip()))
		except ValueError:
			return None
	return None


def clamp_timeout_ms(timeout: int | None) -> int:
	worker = _worker_bash_active()
	default = DEFAULT_TIMEOUT_MS
	max_t = MAX_TIMEOUT_MS
	if worker:
		env_raw = os.environ.get("XEYO_WORKER_BASH_TIMEOUT_MS", "").strip()
		env_default = WORKER_BASH_DEFAULT_TIMEOUT_MS
		if env_raw:
			try:
				env_default = max(1_000, min(WORKER_BASH_MAX_TIMEOUT_MS, int(env_raw)))
			except ValueError:
				pass
		default = env_default
		max_t = WORKER_BASH_MAX_TIMEOUT_MS
	if timeout is None:
		return default
	if timeout < 1:
		return 1
	if timeout > max_t:
		return max_t
	return timeout


@dataclass
class BashInput:
	command: str
	timeout_ms: int = DEFAULT_TIMEOUT_MS
	description: Optional[str] = None
	run_in_background: bool = False
	working_directory: Optional[str] = None


@dataclass
class BashOutput:
	stdout: str = ""
	code: int = 0
	interrupted: bool = False
	timed_out: bool = False
	is_error: bool = False
	return_code_interpretation: str | None = None
	background_task_id: str | None = None
	background_log_path: str | None = None
	#: 42 号：registry 托管的 job（有完成通知 / job_output / job_kill）。
	background_job: bool = False
	#: 前台超时晋升：进程未死移交 registry job（partial 输出在 stdout）。
	promoted: bool = False
	promoted_after_ms: int = 0
	persisted_path: str | None = None
	no_output_expected: bool = False


def parse_input(raw: dict[str, Any]) -> BashInput:
	cmd = raw.get("command")
	if cmd is None:
		command = ""
	else:
		command = str(cmd)

	desc = raw.get("description")
	description = None
	if isinstance(desc, str) and desc.strip():
		description = desc.strip()

	timeout = _coerce_optional_int(raw.get("timeout"))
	if timeout is None:
		timeout = _coerce_optional_int(raw.get("timeout_ms"))

	wd = raw.get("working_directory")
	working_directory = None
	if isinstance(wd, str) and wd.strip():
		working_directory = wd.strip()

	return BashInput(
		command=command,
		timeout_ms=clamp_timeout_ms(timeout),
		description=description,
		run_in_background=_coerce_bool(raw.get("run_in_background"), False),
		working_directory=working_directory,
	)


def validate_input(inp: BashInput) -> dict[str, Any]:
	if not inp.command or not inp.command.strip():
		return {"result": False, "message": "command is required", "errorCode": 0}

	if len(inp.command) > MAX_COMMAND_CHARS:
		return {
			"result": False,
			"message": f"command exceeds {MAX_COMMAND_CHARS} characters",
			"errorCode": 1,
		}

	return {"result": True, "message": "", "errorCode": 0}


def resolve_working_directory(
	inp: BashInput,
	*,
	cwd: str,
) -> dict[str, Any]:
	"""Resolve optional working_directory under session cwd; reject escapes."""
	if not inp.working_directory:
		return {"result": True, "cwd": cwd, "message": "", "errorCode": 0}

	raw = inp.working_directory.strip()
	if not path_in_allowed_working_path(raw, cwd=cwd):
		return {
			"result": False,
			"cwd": cwd,
			"message": f"working_directory escapes workspace: {raw}",
			"errorCode": 3,
		}
	resolved = expand_to_abs(raw, cwd=cwd)
	if not os.path.isdir(resolved):
		return {
			"result": False,
			"cwd": cwd,
			"message": f"working_directory is not a directory: {raw}",
			"errorCode": 4,
		}
	return {"result": True, "cwd": resolved, "message": "", "errorCode": 0}


class BashTool:
	name = BASH_TOOL_NAME

	search_hint = "execute shell commands"

	max_result_size_chars = MAX_RESULT_CHARS

	def __init__(self, *, cwd: str = ".") -> None:
		self._cwd = os.path.abspath(cwd or ".")

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def check_permissions(
		self, inp: BashInput, context: Any = None, *, cwd: str | None = None
	) -> bool:
		"""工具级门禁（纵深防御）：DENY 拒绝；ASK 仅在 registry 已 preapprove 时放行。

		默认用 ``self._cwd`` 评估；调用方可传解析后的 ``working_directory``（``cwd``），
		使策略判定（工作区 policy 加载 / 允许根解析 / 相对路径展开）基于命令实际运行目录。
		"""
		_ = context
		decision = evaluate_policy(
			self.name,
			{"command": inp.command},
			cwd=cwd or self._cwd,
		)
		if decision.decision == PermissionDecision.ALLOW:
			return True
		if decision.decision == PermissionDecision.ASK:
			return permission_preapproved()
		return False

	def call(
		self,
		inp: BashInput,
		*,
		abort: AbortController | None = None,
		cwd: str | None = None,
		loop: Any = None,
	) -> BashOutput:
		timeout_ms = clamp_timeout_ms(inp.timeout_ms)
		run_cwd = cwd if cwd is not None else self._cwd

		# 预检查：只拦「等 TTY/编辑器会挂」的形态；预检自身异常必须 fail-open，
		# 否则一次正则意外就把整个 Bash 工具打挂（call 是 Bash 唯一执行路径）。
		try:
			can_execute, failure_reason = precheck_command(inp.command)
		except Exception:  # noqa: BLE001
			can_execute, failure_reason = True, None
		if not can_execute:
			return BashOutput(
				stdout=fast_fail_message(failure_reason or ""),
				code=1,
				is_error=True,
			)

		if inp.run_in_background:
			# 42 号：优先登记为 registry job（完成通知 / job_output / job_kill）；
			# registry 不可用（CLI in-process）落回旧式日志文件后台，行为不变。
			bridged = start_registry_job(
				command=inp.command.strip(),
				cwd=run_cwd,
				description=inp.description,
				session_id=self._session_id(),
				loop=loop,
			)
			if bridged is not None:
				job_id, err = bridged
				if job_id:
					return BashOutput(background_task_id=job_id, background_job=True)
				# registry 可达但登记失败（容量/会话等）：记录并回退旧式日志文件后台。
				_log.warning(
					"bash background: registry job start failed (%s); "
					"falling back to log-file background",
					err,
				)
			h = start_background(
				inp.command.strip(),
				cwd=run_cwd,
				timeout_ms=timeout_ms,
				description=inp.description,
				abort=abort,
			)
			return BashOutput(
				background_task_id=h.task_id,
				background_log_path=h.log_path,
			)

		cmd = inp.command.strip()
		if abort is not None and abort.aborted:
			return BashOutput(stdout="", code=1, interrupted=True)

		# 前台两阶段：先等 promote 阈值，仍未结束 → 活进程晋升为后台 job
		#（进程不重启、已累积输出随晋升返回）。worker 模式禁晋升。
		promote_ms = 0 if _worker_bash_active() else promote_threshold_ms()
		if promote_ms > 0:
			promote_ms = min(promote_ms, timeout_ms)
		h = spawn_streaming(cmd, cwd=run_cwd, abort=abort)
		promote_started = time.monotonic()
		if (
			h.spawn_error is None
			and promote_ms > 0
			and not h.wait_until(promote_started + promote_ms / 1000.0)
		):
			promoted = self._promote_running(
				h,
				cmd=cmd,
				run_cwd=run_cwd,
				description=inp.description,
				loop=loop,
				abort=abort,
				promote_ms=promote_ms,
			)
			if promoted is not None:
				return promoted
		# 已消耗 promote 等待窗（或未启用晋升），剩余超时 = timeout - 实际已等时长。
		# 用单调时钟精确扣减：避免被 max(1_000, ...) 抬高而突破用户指定的 timeout。
		elapsed_promote = int((time.monotonic() - promote_started) * 1000)
		remaining_ms = (
			max(0, timeout_ms - elapsed_promote) if promote_ms else timeout_ms
		)
		result = finish_streaming(h, timeout_ms=remaining_ms)

		is_error, msg = interpret_command_result(inp.command, result.code)
		if result.interrupted or result.timed_out:
			is_error = True

		stdout = result.stdout or ""
		if (
			is_error
			and result.code != 0
			and not result.interrupted
			and not result.timed_out
		):
			stdout = stdout.rstrip() + f"\nExit code {result.code}"

		# 语义压缩先于硬截断：压 test/build/git 噪声，失败与 traceback 保留。
		stdout = compact_command_output(inp.command, stdout)

		stdout, persisted = truncate_for_model(
			stdout,
			limit=self.max_result_size_chars,
			persist_dir=os.path.join(self._cwd, ".xeyo", "tool-results"),
		)
		return BashOutput(
			stdout=stdout,
			code=result.code,
			interrupted=result.interrupted,
			timed_out=result.timed_out,
			is_error=is_error,
			return_code_interpretation=msg,
			persisted_path=persisted,
			no_output_expected=expect_no_output(inp.command),
		)

	def _promote_running(
		self,
		handle: Any,  # tools.bash_tool.runner.StreamHandle（活进程 + 泵线程）
		*,
		cmd: str,
		run_cwd: str,
		description: str | None,
		loop: Any,
		abort: AbortController | None,
		promote_ms: int,
	) -> BashOutput | None:
		"""前台超时晋升：把仍在运行的活进程移交后台（进程不重启、不重跑）。

		registry 可用 → adopt_registry_job（42 号 job 语义：完成通知/增量）；
		不可用或拒绝 → adopt_background（日志文件后台）；
		两者都失败 → None（调用方继续前台等到 timeout，行为同旧版）。
		返回值携带已累积输出尾部，模型立即拿到部分结果 + job id。
		"""
		partial = handle.tail(4000)
		sid = self._session_id()
		if sid:
			bridged = adopt_registry_job(
				handle=handle,
				command=cmd,
				cwd=run_cwd,
				description=description,
				session_id=sid,
				loop=loop,
			)
			if bridged is not None:
				job_id, _err = bridged
				if job_id:
					return BashOutput(
						background_task_id=job_id,
						background_job=True,
						promoted=True,
						promoted_after_ms=promote_ms,
						stdout=partial,
					)
			# registry 拒绝（容量满/无会话）→ 落回日志文件后台
		try:
			from tools.bash_tool.background import adopt_background

			bh = adopt_background(
				handle, cwd=run_cwd, description=description, parent_abort=abort
			)
		except Exception:  # noqa: BLE001 — 收编全失败 → 继续前台等待
			return None
		return BashOutput(
			background_task_id=bh.task_id,
			background_log_path=bh.log_path,
			promoted=True,
			promoted_after_ms=promote_ms,
			stdout=partial,
		)

	@staticmethod
	def map_tool_result_to_content(out: BashOutput) -> str:
		if out.promoted:
			lines: list[str] = []
			body = (out.stdout or "").strip()
			if body:
				lines.append(
					f"Partial output after {out.promoted_after_ms}ms:\n{body}"
				)
			if out.background_task_id and out.background_job:
				lines.append(
					f"Command still running — auto-moved to background job "
					f"{out.background_task_id} after {out.promoted_after_ms}ms "
					f"(process not restarted; it will notify on completion; "
					f"read with job_output, list with job_list, stop with job_kill)."
				)
			elif out.background_task_id:
				lines.append(
					f"Command still running — auto-moved to background task "
					f"{out.background_task_id} after {out.promoted_after_ms}ms; "
					f"streaming log: {out.background_log_path} (Read it later; "
					f"session abort cancels it)."
				)
			return "\n\n".join(lines) or "Command auto-moved to background."

		if out.background_task_id:
			if out.background_job:
				# 42 号 DSH 同款文案：完成会自动通知；job_output 收结果。
				return (
					f"Started background job {out.background_task_id}. "
					f"It will notify on completion automatically. "
					f"Read its output with job_output (list with job_list, "
					f"stop with job_kill)."
				)
			return (
				f"Command running in background with ID: {out.background_task_id}. "
				f"Output is being written to: {out.background_log_path}. "
				f"Use the Read tool to view it later. "
				f"Session abort cancels this task."
			)

		parts: list[str] = []
		body = (out.stdout or "").replace("\r\n", "\n").lstrip("\n").rstrip()
		if body:
			parts.append(body)
		if out.interrupted:
			parts.append("<error>Command was aborted before completion</error>")
		elif out.timed_out:
			parts.append(
				"<error>Command timed out and was killed</error> "
				f"[shell: {shell_display_name()}]"
			)
		elif out.return_code_interpretation and out.is_error:
			# 正文已含 exit code 时仍保留解释信息
			pass

		if not parts:
			if out.no_output_expected and not out.is_error:
				return "Done"
			if out.return_code_interpretation and not out.is_error:
				return out.return_code_interpretation
			return "(No output)"
		return "\n".join(parts)

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": prompt(),
			"input_schema": {
				"type": "object",
				"properties": {
					"command": {
						"type": "string",
						"description": "The command to execute",
					},
					"timeout": {
						"type": "number",
						"description": (
							f"Optional timeout in milliseconds "
							f"(max {MAX_TIMEOUT_MS}); a foreground command "
							f"still running after ~45s is auto-moved to a "
							f"background job instead of blocking"
						),
					},
					"description": {
						"type": "string",
						"description": (
							"Clear, concise description of what this command does"
						),
					},
					"run_in_background": {
						"type": "boolean",
						"description": (
							"Set true to run in background: returns a job id "
							"immediately, notifies on completion; read output "
							"with job_output."
						),
					},
					"working_directory": {
						"type": "string",
						"description": (
							"Optional cwd for this command (relative to session cwd). "
							"Must stay under the allowed workspace."
						),
					},
				},
				"required": ["command"],
			},
		}

	async def execute(
		self,
		input: dict[str, Any],
		abort: AbortController,
	) -> ToolResult:
		abort.raise_if_aborted()
		inp = parse_input(input)
		v = validate_input(inp)
		if not v.get("result"):
			return ToolResult(content=str(v.get("message")), is_error=True)
		if _worker_bash_active() and inp.run_in_background:
			return ToolResult(
				content="sub-agent Bash cannot run in background",
				is_error=True,
			)
		resolved = resolve_working_directory(inp, cwd=self._cwd)
		if not resolved.get("result"):
			return ToolResult(content=str(resolved.get("message")), is_error=True)
		work = str(resolved["cwd"])
		if not self.check_permissions(inp, cwd=work):
			return ToolResult(content="permission denied", is_error=True)
		abort.raise_if_aborted()
		git_op = self._begin_presence(work, inp.command)
		try:
			# P0: run_command 是同步阻塞（proc.communicate 最长 600s），
			# 必须挪出事件循环，否则一次长命令会冻结整个服务。
			# 42 号：loop 传给后台分支，registry 借它调度唤醒决策（settle
			# 发生在 worker 线程，需 call_soon_threadsafe 代理回事件循环）。
			try:
				_loop: Any = asyncio.get_running_loop()
			except RuntimeError:
				_loop = None
			out = await asyncio.to_thread(
				self.call, inp, abort=abort, cwd=work, loop=_loop
			)
		except Exception as e:  # noqa: BLE001
			self._end_presence(work, git_op)
			return ToolResult(content=str(e), is_error=True)
		self._end_presence(work, git_op)
		abort.raise_if_aborted()
		self._note_bash_write_target(work, inp.command)
		return ToolResult(
			content=self.map_tool_result_to_content(out),
			is_error=bool(out.is_error),
		)

	def _session_id(self) -> str:
		try:
			from engine.workspace_context import get_workspace_context

			ctx = get_workspace_context()
			if ctx is not None and ctx.session_id:
				return str(ctx.session_id).strip()
		except Exception:  # noqa: BLE001
			pass
		return ""

	def _begin_presence(self, cwd: str, command: str) -> str | None:
		sid = self._session_id()
		if not sid:
			return None
		try:
			from engine.session_presence import (
				default_session_presence,
				detect_git_write_op,
			)

			op = detect_git_write_op(command)
			if op:
				default_session_presence().note_git(cwd, sid, op)
			return op
		except Exception:  # noqa: BLE001
			return None

	def _end_presence(self, cwd: str, git_op: str | None) -> None:
		if not git_op:
			return
		sid = self._session_id()
		if not sid:
			return
		try:
			from engine.session_presence import default_session_presence

			default_session_presence().note_git(cwd, sid, None)
		except Exception:  # noqa: BLE001
			pass

	def _note_bash_write_target(self, cwd: str, command: str) -> None:
		"""能解析出写目标时记入 presence（不假装能锁未解析路径）。"""
		sid = self._session_id()
		if not sid:
			return
		try:
			from permissions.policy import bash_write_target, bash_writes_file
			from permissions.filesystem import expand_to_abs
			from engine.session_presence import default_session_presence

			if not bash_writes_file(command):
				return
			target = bash_write_target(command)
			if not target:
				return
			path = expand_to_abs(target, cwd=cwd)
			default_session_presence().note_write(cwd, sid, path)
		except Exception:  # noqa: BLE001
			pass
