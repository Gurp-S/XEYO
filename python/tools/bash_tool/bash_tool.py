"""BashTool — Shell 执行器 (P0).

模型填参数 → validate → checkPermissions(stub) → call → semantics → truncate → map
"""

# TODO: [测试] 语义 exit、截断（Windows 编码 / 复合命令 / 后台转档已有专项测试）

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)

# docker 路由的后台 job 表（评测场景自持；registry 依赖 server，headless 不可用）
_DOCKER_BG_JOBS: dict[str, dict] = {}
_DOCKER_BG_LOCK = threading.Lock()
_DOCKER_BG_SEQ = 0

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
from tools.container_routing import current_container as _routed_container
from tools.bash_tool.jobs_bridge import adopt_registry_job, start_registry_job
from tools.bash_tool.prompt import BASH_TOOL_NAME, DESCRIPTION
from tools.bash_tool.runner import (
	finish_streaming,
	shell_display_name,
	spawn_streaming,
)
from tools.bash_tool.semantics import (
	_split_segment,
	extract_base_command,
	interpret_command_result,
)
from tools.bash_tool.truncate import truncate_for_model
from tools.bash_tool.destructive_guard import (
	plan_destructive_snapshot,
	settle_destructive_plan,
)
from tools.bash_tool.precheck import precheck_command

# ====== 搜索缓存门控失效（2026-09-09，A1 扩展：Bash 是第二条写盘路径）======
# Write/Edit 走各自 _persist 漏斗已失效 glob 缓存；Bash 改文件（echo>/
# sed -i/npm install...）此前不触发，留 60s/30s"写后看不见"窗口。
# fail-closed：只读白名单全命中才保留缓存；解释器/未知/解析失败一律判写。
# 误清只损失一次缓存重建（~140ms），漏清是正确性事故——误差单向朝安全。

# 纯读基础命令（任意参数都只读；重定向/命令替换另行拦截）。
_PURE_READ_BASES = frozenset({
	"ls", "dir", "cat", "type", "head", "tail", "rg", "grep", "findstr",
	"wc", "stat", "du", "df", "file", "ps", "tasklist", "whoami",
	"hostname", "pwd", "date", "printenv", "which", "where", "echo",
	"printf", "test", "true", "false", "sleep", "uname", "id", "tty",
	"basename", "dirname", "realpath", "readlink", "cut", "uniq", "tr",
	"column", "nl", "tac", "rev", "fold", "fmt", "join", "cmp", "diff",
	"comm", "cksum", "md5sum", "sha1sum", "sha256sum", "iconv", "xxd",
	"od", "hexdump", "strings", "tree", "free", "uptime", "ver", "vol",
	"git",  # git 另查子命令白名单
})
_GIT_READ_SUBS = frozenset({
	"status", "log", "diff", "show", "blame", "rev-parse", "describe",
	"shortlog", "ls-files", "ls-remote", "cat-file", "grep", "reflog",
	"version", "help",
})


def _segment_base(seg: str) -> str:
	token = seg.strip().split()[0] if seg.strip() else ""
	if "/" in token or "\\" in token:
		token = token.replace("\\", "/").rsplit("/", 1)[-1]
	if token.lower().endswith(".exe"):
		token = token[:-4]
	return token.lower()


def _command_may_mutate_workspace(command: str) -> bool:
	"""Bash 命令是否可能写盘 → 是否应失效搜索缓存。"""
	if not command or not command.strip() or "\n" in command:
		return True  # 空/多行不可解析 → fail-closed
	try:
		from permissions.policy import bash_writes_file

		if bash_writes_file(command):
			return True  # 显式写特征（重定向/写命令/解释器带写标记）
	except Exception:
		return True  # 分类器不可用 → fail-closed
	if "$(" in command or "`" in command:
		return True  # 命令替换可藏任意写
	for seg in _split_segment(command):
		base = _segment_base(seg)
		if base == "git":
			sub = _segment_base(" ".join(seg.strip().split()[1:]))
			if sub not in _GIT_READ_SUBS:
				return True
		elif base not in _PURE_READ_BASES:
			return True
	return False


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


#: 收尾窗内"立即后台化长命令"的剩余时间闸门（秒）。窗口还剩很多时不动——让
#: 可能在窗口内跑完的命令照常前台等结果（保住"最后一步长命令出产物"的路径）；
#: 只在窗口已经很短（或剩余时间未知=配额型收尾窗）时才提前交还控制权。
WRAP_WINDOW_BG_MAX_REMAINING_S = 120.0


def effective_promote_ms(cmd: str, base_ms: int) -> int:
	"""收尾窗内**时间不够**的长命令族 → 1ms（立即后台化），否则原样返回。

	窗口（R1'/R3' 的 forced_wrap_up）只剩几十秒时，等 promote 阈值（默认 45s）
	等于把落盘时间吃掉；提前交还控制权，模型就能用余下时间落盘。这是**执行层
	路由决策**，不向模型输出任何劝告文本。

	不触发的情况（保持旧行为）：不在窗口内 / 非长命令族 / base_ms<=0 /
	窗口剩余时间充裕（>= WRAP_WINDOW_BG_MAX_REMAINING_S，让能跑完的命令照常等）。
	"""

	if base_ms <= 0:
		return base_ms
	try:
		from engine.wrap_window import in_wrap_window, wrap_remaining_s
		from tools.bash_tool.timeout_map import family_default_ms

		if not in_wrap_window():
			return base_ms
		if family_default_ms(cmd) is None:
			return base_ms
		remaining = wrap_remaining_s()
		if remaining is not None and remaining >= WRAP_WINDOW_BG_MAX_REMAINING_S:
			return base_ms
		return 1
	except Exception:  # noqa: BLE001 — 信号/映射不可用即按原阈值
		return base_ms
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


def _docker_exec_with_timeout(
	cid: str,
	command: str,
	timeout_ms: int,
) -> tuple[int, str]:
	"""经 docker SDK 在容器内执行命令（named pipe 直连，零宿主 shell 依赖）。

	promote 等价物（评测路由分支）：promote 阈值（默认 45s，XEYO_BASH_PROMOTE_MS
	可覆盖）内完成 → 直接返回；超时 → 命令转「docker 后台 job」（worker 线程继续
	跑完写入 `_DOCKER_BG_JOBS`），立即把控制权还给模型并告知 job_id——长命令不再
	阻塞回合（复现：p90 间隔 77-407s 的长命令曾把 15 分钟预算吃光）。完成状态经
	`job_list` / `pending_jobs_block` 镜像给模型，输出用 `job_output` 领取。
	"""
	import queue
	import threading

	q: "queue.Queue[tuple[int, str]]" = queue.Queue()
	job_box: dict = {"id": None}

	def _worker() -> None:
		try:
			import docker

			client = docker.from_env()
			res = client.containers.get(cid).exec_run(
				["bash", "-lc", command], demux=True
			)
			out_b, err_b = res.output
			text = ((out_b or b"") + (err_b or b"")).decode("utf-8", "replace")
			code = int(res.exit_code or 0)
		except Exception as exc:  # noqa: BLE001
			code, text = 95, f"docker exec failed: {exc}"
		q.put((code, text))
		jid = job_box.get("id")
		if jid:
			with _DOCKER_BG_LOCK:
				job = _DOCKER_BG_JOBS.get(jid)
				if job is not None:
					job["status"] = "done"
					job["output"] = text
					job["exit_code"] = code

	promote_s = _docker_promote_seconds()
	try:
		promote_s = max(1.0, min(promote_s, timeout_ms / 1000))
	except Exception:  # noqa: BLE001
		promote_s = 45.0

	# 快路径：阈值内完成 → 直接返回
	threading.Thread(
		target=_worker, daemon=True, name="xeyo-docker-exec"
	).start()
	try:
		return q.get(timeout=promote_s)
	except queue.Empty:
		pass

	# 晋升：先确认 worker 未恰好完成（竞态窗口），再登记后台 job——
	# 原 worker 继续跑（零重复执行），完成后经 job_box 桥写入 job 表。
	try:
		return q.get_nowait()
	except queue.Empty:
		pass
	global _DOCKER_BG_SEQ
	with _DOCKER_BG_LOCK:
		_DOCKER_BG_SEQ += 1
		job_id = f"bash-{_DOCKER_BG_SEQ}"
		_DOCKER_BG_JOBS[job_id] = {
			"status": "running",
			"output": "",
			"exit_code": None,
			"command": command,
			"delivered": False,
			"started": time.time(),
		}
	job_box["id"] = job_id
	return (
		0,
		f"[命令仍在运行，已自动转入后台 job {job_id}。**不要等待它完成**——立即继续"
		f"其他工作；完成通知会在下一回合自动出现，届时用 job_output(job_id=\"{job_id}\")"
		f"（不要传 wait=true，会白等）领取输出]\n已累积输出：\n",
	)


def _docker_promote_seconds() -> float:
	try:
		return float(os.environ.get("XEYO_BASH_PROMOTE_MS", "45000")) / 1000
	except Exception:  # noqa: BLE001
		return 45.0


def docker_bg_snapshot() -> list[dict]:
	"""外部只读视图（job_tools 回退 / pending_jobs_block 镜像用）。"""
	with _DOCKER_BG_LOCK:
		return [
			{"job_id": k, **{kk: vv for kk, vv in v.items()}}
			for k, v in _DOCKER_BG_JOBS.items()
		]


def docker_bg_mark_delivered(job_id: str) -> None:
	with _DOCKER_BG_LOCK:
		job = _DOCKER_BG_JOBS.get(job_id)
		if job is not None:
			job["delivered"] = True


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
	#: 禀赋②：净室执行——在只含 isolation_inputs 的临时目录里跑命令，
	#  验证交付物"离开会话上下文仍然可用"。信息给足，判断归模型。
	run_isolated: bool = False
	isolation_inputs: list[str] = field(default_factory=list)


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
	# #15：模型未显式传 timeout 时按命令族给分级默认（pip/编译等长命令
	# 免 120s 一刀切被掐）。worker（子 Agent）模式不生效——30s/60s 是
	# 刻意的花钱护栏，不让命令族覆盖。纯查表、不碰 LLM 判断。
	if timeout is None and not _worker_bash_active():
		try:
			from tools.bash_tool.timeout_map import family_default_ms

			timeout = family_default_ms(cmd)
		except Exception:  # noqa: BLE001 — 映射失败回落全局默认，不阻断执行
			timeout = None

	wd = raw.get("working_directory")
	working_directory = None
	if isinstance(wd, str) and wd.strip():
		working_directory = wd.strip()

	run_isolated = _coerce_bool(raw.get("run_isolated"), False)
	isolation_inputs: list[str] = []
	raw_inputs = raw.get("isolation_inputs")
	if isinstance(raw_inputs, list):
		isolation_inputs = [str(p) for p in raw_inputs if isinstance(p, str) and p.strip()]

	return BashInput(
		command=command,
		timeout_ms=clamp_timeout_ms(timeout),
		description=description,
		run_in_background=_coerce_bool(raw.get("run_in_background"), False),
		working_directory=working_directory,
		run_isolated=run_isolated,
		isolation_inputs=isolation_inputs,
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
		self._shell_notice_sent = False

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

		# 禀赋②：净室执行——在只含声明输入的临时目录里跑命令（信息给足，判断归模型）。
		# 组合为 POSIX 片段后随同路由（容器内 mktemp/cp 均可用），与容器路由正交。
		if inp.run_isolated:
			inputs = [p.strip().lstrip("/") for p in inp.isolation_inputs if p.strip()]
			cp_part = ("cp --parents " + " ".join(shlex.quote(p) for p in inputs) + " \"$__iso/\" 2>&1; ") if inputs else ""
			composed = (
				'__iso="$(mktemp -d)"; '
				+ cp_part
				+ 'cd "$__iso" || exit 95; '
				+ "{ " + inp.command + "; __rc=$?; } ; "
				+ 'echo "__ISO_DIR=$__iso"; '
				+ 'echo "__ISOLATED_NEW_FILES:"; find "$__iso" -type f | head -40; exit $__rc'
			)
			inp = BashInput(
				command=composed,
				timeout_ms=inp.timeout_ms,
				run_in_background=inp.run_in_background,
				description=inp.description,
			)

		# 容器路由（评测适配）：XEYO_DOCKER_CONTAINER 设置时，所有命令经 docker SDK
		# exec_run 直连 named pipe 转发进容器（bash -lc）。之所以不走宿主 shell 拼串
		#（XEYO_BASH_EXEC_PREFIX 的 docker exec … 方案）：Windows 上 pwsh7 -Command
		# 下 docker exec 的 stdout 会静默丢失（实测 rc=0 空输出，模型全程盲打），
		# SDK 走 API 无 shell/TTY/wsl 依赖，输出与退出码可靠。cwd 语义由 WORKDIR 承担。
		# 并发 trial 防串线：ContextVar（每 trial 协程上下文）优先于进程级 env——
		# harbor 多 trial 共进程时后者会被互相覆盖（p4 冒烟实测串线事故）。
		cid = _routed_container() or os.environ.get("XEYO_DOCKER_CONTAINER", "").strip()
		if cid:
			out_code, out_text = _docker_exec_with_timeout(
				cid, inp.command, timeout_ms
			)
			return BashOutput(code=out_code, stdout=out_text)

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
			# registry 直通路径生产者线程无 rewind ctx（Phase A 已知缺口）；
			# 仅登记失败落回日志文件后台时做 before 快照保护。
			guard_plan = plan_destructive_snapshot(inp.command, run_cwd)
			h = start_background(
				inp.command.strip(),
				cwd=run_cwd,
				timeout_ms=timeout_ms,
				description=inp.description,
				abort=abort,
				guard_plan=guard_plan,
			)
			return BashOutput(
				background_task_id=h.task_id,
				background_log_path=h.log_path,
			)

		cmd = inp.command.strip()
		if abort is not None and abort.aborted:
			return BashOutput(stdout="", code=1, interrupted=True)

		# #14 Phase A：破坏性命令（rm/mv/del…）执行前做 before 快照并登记
		# started 操作；fail-open，返回 None = 本命令不保护。ctx 经 contextvars
		# 在此处捕获（早于任何线程 spawn）。
		guard_plan = plan_destructive_snapshot(cmd, run_cwd)

		# 前台两阶段：先等 promote 阈值，仍未结束 → 活进程晋升为后台 job
		#（进程不重启、已累积输出随晋升返回）。worker 模式禁晋升。
		promote_ms = 0 if _worker_bash_active() else promote_threshold_ms()
		if promote_ms > 0:
			promote_ms = min(promote_ms, timeout_ms)
			# 收尾窗内长命令族立即后台化（见 effective_promote_ms 注释）。
			promote_ms = effective_promote_ms(cmd, promote_ms)
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
				guard_plan=guard_plan,
			)
			if promoted is not None:
				if guard_plan is not None and promoted.background_job:
					# registry 收编路径无内部结算钩子：守护 poller 跟踪原
					# 进程，结束时结算（adopt_background 路径由其 worker 结算）。
					self._settle_guard_when_proc_ends(h, guard_plan)
				return promoted
		# 已消耗 promote 等待窗（或未启用晋升），剩余超时 = timeout - 实际已等时长。
		# 用单调时钟精确扣减：避免被 max(1_000, ...) 抬高而突破用户指定的 timeout。
		elapsed_promote = int((time.monotonic() - promote_started) * 1000)
		remaining_ms = (
			max(0, timeout_ms - elapsed_promote) if promote_ms else timeout_ms
		)
		result = finish_streaming(h, timeout_ms=remaining_ms)

		# 破坏性命令已有结局：执行过（含非零退出/中断/超时）→ completed；
		# spawn 失败根本没跑 → cancelled。settle 自身 fail-open。
		settle_destructive_plan(guard_plan, executed=h.spawn_error is None)

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
		# 会话内首个成功结果带一次 shell 身份行（Windows 实为 PowerShell/pwsh，
		# 模型若不读工具描述会先试 bash 语法白烧一轮）。只发一次，不常驻计费。
		if (
			not self._shell_notice_sent
			and os.name == "nt"
			and stdout
			and not is_error
			and not result.interrupted
			and not result.timed_out
			and not expect_no_output(inp.command)
		):
			self._shell_notice_sent = True
			stdout = f"[shell: {shell_display_name()}]\n" + stdout
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
		guard_plan: Any = None,
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
				handle, cwd=run_cwd, description=description, parent_abort=abort,
				guard_plan=guard_plan,
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
	def _settle_guard_when_proc_ends(handle: Any, guard_plan: Any) -> None:
		"""registry 收编后的 guard 结算：守护线程跟踪原进程，结束时结算。

		adopt_registry_job 内部不感知 rewind（Phase A 缺口），故由 call 在
		晋升返回后挂此 poller；持有裸 proc 引用，release() 置空 handle.proc
		不影响跟踪。双重结算安全（completed → completed 是合法 no-op）。
		"""

		if guard_plan is None:
			return
		proc = getattr(handle, "proc", None)
		if proc is None:
			settle_destructive_plan(guard_plan, executed=True)
			return

		def _poll() -> None:
			try:
				while proc.poll() is None:
					time.sleep(0.5)
			except Exception:  # noqa: BLE001 — 进程对象异常也必须结算
				pass
			settle_destructive_plan(guard_plan, executed=True)

		threading.Thread(target=_poll, name="bash-guard-settle", daemon=True).start()

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
				# 42 号文案：完成会自动通知；job_output 收结果。
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
					"run_isolated": {
						"type": "boolean",
						"description": (
							"Run in a clean temporary directory containing ONLY "
							"isolation_inputs. Use to verify a deliverable works "
							"outside your session context (missing files will "
							"surface as normal errors)"
						),
					},
					"isolation_inputs": {
						"type": "array",
						"items": {"type": "string"},
						"description": (
							"Paths (relative to cwd) copied into the isolated "
							"directory before execution; empty = no inputs"
						),
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
			self._invalidate_search_caches(inp.command, background=inp.run_in_background)
			return ToolResult(content=str(e), is_error=True)
		self._end_presence(work, git_op)
		abort.raise_if_aborted()
		self._note_bash_write_target(work, inp.command)
		self._invalidate_search_caches(inp.command, background=inp.run_in_background)
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
			_log.debug("session presence note_git failed", exc_info=True)

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
			_log.debug("session presence note_write failed", exc_info=True)

	def _invalidate_search_caches(self, command: str, *, background: bool = False) -> None:
		"""Bash 执行后门控失效 Glob/Grep 搜索缓存（A1 扩展，2026-09-09）。

		后台命令不透明（执行期才写盘）→ 一律清；前台命令按
		_command_may_mutate_workspace 门控。失效失败不影响 Bash 主路径。
		"""
		if not background:
			try:
				if not _command_may_mutate_workspace(command):
					return
			except Exception:  # noqa: BLE001
				pass  # 分类器异常 → 继续清（正确性优先）
		try:
			from tools.glob_tool.glob_tool import clear_glob_cache
			from tools.fileio.content_index import clear_content_index

			clear_glob_cache()
			clear_content_index()
		except Exception:  # noqa: BLE001
			pass
