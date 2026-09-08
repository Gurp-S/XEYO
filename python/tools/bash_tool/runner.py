"""Shell 执行底层：PowerShell 解析器 + 流式 spawn（前台超时晋升的基础设施）。

- ``build_shell_argv``：pwsh 7（env → PATH → 内置缓存，见 pwsh7.locate）→
  PowerShell 5.1 兜底 → POSIX /bin/sh。argv 向量 + ``shell=False``，
  杜绝 cmd 套壳的双层引号；结果只解一层。
- ``spawn_streaming``：启动进程 + 泵线程（行级解码 → buf + sinks）+ abort 监视。
  前台/后台共用；前台可在任意 deadline 上 ``wait_until``，未退出则把**活进程**
  整体晋升为 registry job（bash_tool.call → jobs_bridge.adopt_registry_job）。
- ``run_command``：兼容旧签名（background.py / job_registry 依赖），语义等价：
  stdout/stderr 合并、超时杀树、abort 杀树、UTF-8→GBK 回退解码。
- sink 约定：不得回调 StreamHandle 自身（持锁期间调用会死锁）。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from engine.abort import AbortController
from tools.bash_tool.win_job import JobHandle, create_bash_job

#: 泵线程结束后等待残余输出的上限（秒）
_PUMP_DRAIN_S = 2.0


def _utf8_env() -> dict[str, str]:
	"""Windows 中文编码根治：让子进程（尤其 python/powershell）统一按 UTF-8 处理。

	- PYTHONUTF8=1        → python -c/-m 源码、sys.argv、文件系统编码、stdio 均为 UTF-8
	- PYTHONIOENCODING=utf-8 → python 的 stdin/stdout/stderr 用 UTF-8（避免 GBK 输出被误读）
	- PYTHONLEGACYWINDOWSSTDIO=0 → 关闭历史遗留的 Windows 窄/宽 stdio 转换
	"""
	env = os.environ.copy()
	env.setdefault("PYTHONUTF8", "1")
	env.setdefault("PYTHONIOENCODING", "utf-8")
	env.setdefault("PYTHONLEGACYWINDOWSSTDIO", "0")
	env.setdefault("PYTHONLEGACYWINDOWSFSENCODING", "0")
	return env


@dataclass
class ExecResult:
	stdout: str
	code: int
	interrupted: bool = False
	timed_out: bool = False


def _job_memory_mb(cwd: str) -> int | None:
	try:
		from permissions.workspace_policy import load_workspace_policy

		return load_workspace_policy(cwd).bash_job_memory_mb
	except Exception:
		return None


def _kill_process(proc: subprocess.Popen, job: JobHandle | None = None) -> None:
	"""终止仍在运行的进程树。

	优先 taskkill /T（可靠打断 shell 子进程）；Job Object 仅作限额与
	CloseHandle 时的 KillOnJobClose 兜底——勿在此调用 TerminateJobObject，
	在部分嵌套 Job 环境下会阻塞。
	"""
	_ = job
	if proc is None or proc.poll() is not None:
		return
	try:
		if os.name == "nt" and proc.pid:
			# shell=False 时杀的也是整棵树（taskkill /T）；proc.kill() 仅杀根。
			subprocess.run(
				["taskkill", "/PID", str(proc.pid), "/T", "/F"],
				capture_output=True,
				timeout=5,
				check=False,
			)
		else:
			proc.kill()
		try:
			proc.wait(timeout=2)
		except subprocess.TimeoutExpired:
			pass
	except OSError:
		pass


def _decode(data: bytes) -> str:
	"""按 UTF-8 优先、OEM/GBK 回退解码子进程输出，根治中文乱码。

	Windows PowerShell 5.1 的部分原生输出仍走 OEM/GBK 码页；python/rg/git 等
	已按 UTF-8（见 ``_utf8_env``）。纯 UTF-8 解码失败（如 GBK 汉字）→ 回退
	GBK/cp936，避免中文文件名输出 ``***********`` 乱码。可作任意字节块解码。
	"""
	if not data:
		return ""
	for codec in ("utf-8", "gbk", "cp1252"):
		try:
			return data.decode(codec)
		except UnicodeDecodeError:
			continue
	return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# shell 解析：PowerShell 7 → 5.1 兜底（argv 向量，非套壳）
# ---------------------------------------------------------------------------

_SHELL_META_CACHE: dict[str, str] = {}
_SHELL_META_LOCK = threading.Lock()


def _ps51_exe() -> str:
	root = os.environ.get("SystemRoot", r"C:\Windows")
	return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _resolve_pwsh_exe() -> tuple[str | None, str]:
	"""返回 (pwsh.exe 路径 | None, kind)。不下载、不阻塞；仅文件存在性判断。"""
	if os.environ.get("XEYO_DISABLE_PWSH7", "").strip().lower() in ("1", "true", "yes"):
		return None, "powershell"
	try:
		from tools.bash_tool.pwsh7 import locate

		p = locate()
		if p is not None:
			return str(p), "pwsh"
	except Exception:  # noqa: BLE001 — pwsh7 引导器不可用不致命
		pass
	return None, "powershell"


def build_shell_argv(command: str) -> tuple[list[str], str]:
	"""构造 shell 调用向量。command 不参与解析器选择（仅占位签名）。

	返回 (argv 前缀, 显示名)。最终 Popen 为 ``[*argv, command]``、``shell=False``。
	"""
	_ = command
	if os.name != "nt":
		return ["/bin/sh", "-c"], "sh"
	exe, kind = _resolve_pwsh_exe()
	if kind == "pwsh" and exe:
		return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"], "pwsh"
	return [_ps51_exe(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"], "powershell"


def shell_display_name() -> str:
	"""探测 shell 版本（进程内缓存一次），用于结果头元信息与诊断。"""
	argv, kind = build_shell_argv("")
	exe = argv[0]
	with _SHELL_META_LOCK:
		cached = _SHELL_META_CACHE.get(exe)
	if cached is not None:
		return cached
	name = f"{kind} (version unavailable)"
	try:
		proc = subprocess.run(
			[
				exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
				"$PSVersionTable.PSVersion.ToString()",
			],
			capture_output=True,
			timeout=8,
			env=_utf8_env(),
		)
		lines = _decode(proc.stdout or b"").strip().splitlines()
		if lines and lines[-1].strip():
			name = f"{kind} {lines[-1].strip()}"
	except Exception:  # noqa: BLE001 — 元信息探测失败不影响执行
		pass
	with _SHELL_META_LOCK:
		_SHELL_META_CACHE[exe] = name
	return name


# ---------------------------------------------------------------------------
# 流式 spawn（前台/后台共用底座）
# ---------------------------------------------------------------------------

SinkFn = Callable[[str], None]

# P3 旁路:副作用台账登记(env XEYO_PROC_LEDGER 门控,默认关;关时零行为差异)。
# 导入失败绝不拖垮 bash 主路径。
try:
	from engine.process_ledger import (
		register_process as _ledger_register_process,
		unregister_process as _ledger_unregister_process,
	)
except Exception:  # noqa: BLE001 — 台账不可用 → 全空操作
	_ledger_register_process = lambda *a, **k: False
	_ledger_unregister_process = lambda *a, **k: False


@dataclass
class StreamHandle:
	"""一次流式 spawn 的句柄：活进程 + 泵缓冲 + 可后挂的 sink。"""

	proc: subprocess.Popen | None
	job: JobHandle | None
	spawn_error: str | None = None
	buf: list[str] = field(default_factory=list)
	sinks: list[SinkFn] = field(default_factory=list)
	killed_by_abort: bool = False
	buf_lock: threading.Lock = field(default_factory=threading.Lock)
	_pump_done: threading.Event = field(default_factory=threading.Event)
	_release_lock: threading.Lock = field(default_factory=threading.Lock)
	_released: bool = False
	#: [AbortController | None] 可变槽：attach/detach 原语换内容，监视线程每轮读槽。
	_abort_box: list = field(default_factory=list)
	_watcher_started: bool = False

	# -- 泵送 ------------------------------------------------------------
	def start_pump(self) -> None:
		if self.proc is None or self.proc.stdout is None:
			self._pump_done.set()
			return
		threading.Thread(
			target=self._pump, name="bash-pump", daemon=True
		).start()

	def _pump(self) -> None:
		try:
			for raw in self.proc.stdout:  # type: ignore[union-attr]
				text = _decode(raw)
				with self.buf_lock:
					self.buf.append(text)
					sinks = tuple(self.sinks)
				for sink in sinks:
					try:
						sink(text)
					except Exception:  # noqa: BLE001 — 消费方异常不拖垮泵
						pass
		except Exception:  # noqa: BLE001 — 进程被杀时 readline 抛错属正常收尾
			pass
		finally:
			self._pump_done.set()

	# -- 汇 / 缓冲 ----------------------------------------------------
	def add_sink(self, sink: SinkFn) -> None:
		with self.buf_lock:
			self.sinks.append(sink)

	def buffered(self) -> str:
		with self.buf_lock:
			return "".join(self.buf)


	def tail(self, n: int = 4000) -> str:
		text = self.buffered()
		return text[-n:] if len(text) > n else text

	# -- abort / wait / 终结 ------------------------------------------------
	def watch_abort(self, abort: AbortController | None) -> None:
		"""设置 abort 槽并确保监视线程在跑。spawn 后总调用一次（None 也启动）。"""
		if not self._abort_box:
			self._abort_box.append(abort)
		else:
			self._abort_box[0] = abort
		if not self._watcher_started:
			self._watcher_started = True
			threading.Thread(
				target=self._watch, args=(abort,), name="bash-abort-watch", daemon=True
			).start()

	attach_abort = watch_abort  # 晋升/收编后换绑 ctl（registry ctl / merged abort）


	def replay_and_attach(self, sink: SinkFn) -> str:
		"""原子的「取走已缓冲输出 + 挂上新 sink」（晋升收编用，防丢行）。

		返回已缓冲文本，由调用方决定去向（registry ring 先推 / log 先写）。
		注：attach 后泵线程新行直接进 sink，replay 文本由调用方补推，
		接缝处个别行顺序可能颠倒（ring 保尾 / log 均可接受）。
		"""
		with self.buf_lock:
			text = "".join(self.buf)
			self.buf.clear()
			self.sinks.append(sink)
		return text

	def _watch(self, abort: AbortController | None) -> None:
		proc = self.proc
		if proc is None:
			return
		while proc.poll() is None:
			current = self._abort_box[0] if self._abort_box else abort
			if current is not None and current.aborted:
				self.killed_by_abort = True
				self.kill()
				return
			time.sleep(0.05)

	def kill(self) -> None:
		if self.proc is not None:
			_kill_process(self.proc, self.job)

	def wait_until(self, deadline: float) -> bool:
		"""等到 deadline；返回是否已退出（晋升判定用）。不杀进程。"""
		if self.spawn_error is not None:
			return True
		remaining = deadline - time.monotonic()
		try:
			if remaining <= 0:
				return self.proc.poll() is not None  # type: ignore[union-attr]
			self.proc.wait(timeout=remaining)  # type: ignore[union-attr]
			return True
		except subprocess.TimeoutExpired:
			return False

	def release(self) -> None:
		"""终结句柄：必要时杀进程、等泵收尾、关 Job Object（幂等）。"""
		with self._release_lock:
			if self._released:
				return
			self._released = True
		if self.proc is not None:
			# 台账除名:释放=引擎责任终止。kill 失败而逃逸的进程成为台账孤儿,
			# 由后续 sweep/收口处置(旁路默认只登记不自动杀)。
			_ledger_unregister_process(self.proc.pid)
		if self.proc is not None and self.proc.poll() is None:
			_kill_process(self.proc, self.job)
		self._pump_done.wait(_PUMP_DRAIN_S)
		if self.job is not None:
			try:
				self.job.close()
			except Exception:  # noqa: BLE001
				pass


def spawn_streaming(
	command: str,
	*,
	cwd: str,
	abort: AbortController | None = None,
	on_output: SinkFn | None = None,
) -> StreamHandle:
	"""启动命令并立即返回句柄。失败不抛（spawn_error 记录，wait_until 视为已退出）。"""
	cwd = os.path.abspath(cwd or ".")
	argv, _kind = build_shell_argv(command)
	job = create_bash_job(memory_mb=_job_memory_mb(cwd))
	try:
		proc = subprocess.Popen(
			[*argv, command],
			cwd=cwd,
			env=_utf8_env(),
			shell=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			stdin=subprocess.DEVNULL,
		)
	except OSError as err:
		job.close()
		h = StreamHandle(
			proc=None, job=None, spawn_error=f"Failed to start command: {err}"
		)
		h._pump_done.set()
		return h
	if proc.pid:
		job.assign(proc.pid)
	_ledger_register_process(proc.pid, cmdline=command)
	h = StreamHandle(proc=proc, job=job)
	if on_output is not None:
		h.add_sink(on_output)
	h.start_pump()
	# 总是启动监视线程：晋升时 detach/attach 换槽即可，无需重启线程。
	h.watch_abort(abort)
	return h


def finish_streaming(h: StreamHandle, *, timeout_ms: int) -> ExecResult:
	"""在已 spawn 的句柄上等完/超时杀树，产出与旧 run_command 等价的 ExecResult。"""
	if h.spawn_error is not None:
		return ExecResult(stdout=h.spawn_error, code=1)
	timed_out = False
	try:
		h.proc.wait(timeout=max(0.001, timeout_ms / 1000.0))  # type: ignore[union-attr]
	except subprocess.TimeoutExpired:
		timed_out = True
		h.kill()
		try:
			h.proc.wait(timeout=2)  # type: ignore[union-attr]
		except subprocess.TimeoutExpired:
			pass
	h.release()
	stdout = h.buffered()
	code = h.proc.returncode if h.proc is not None and h.proc.returncode is not None else 1
	if timed_out:
		return ExecResult(
			stdout=(
				f"Command timed out after {timeout_ms}ms and was killed.\n"
				f"Partial output:\n{stdout or ''}"
			),
			code=code or 1,
			timed_out=True,
		)
	if h.killed_by_abort:
		return ExecResult(
			stdout=(stdout or "").rstrip() + "\n",
			code=code or 1,
			interrupted=True,
		)
	return ExecResult(stdout=stdout or "", code=code)


def run_command(
	command: str,
	*,
	cwd: str,
	timeout_ms: int,
	abort: AbortController | None = None,
	on_output: SinkFn | None = None,
) -> ExecResult:
	"""前台执行一条命令（兼容旧签名；内部走 spawn_streaming 流式底座）。

	- Windows: pwsh7/5.1 argv 向量（shell=False）+ Job Object 内存上限/整树终止
	- stdout/stderr 合并
	- abort 轮询杀进程
	- on_output：提供时逐行回调输出（后台任务实时写 log），不积压 PIPE。
	"""
	if abort is not None and abort.aborted:
		return ExecResult(stdout="", code=1, interrupted=True)
	h = spawn_streaming(command, cwd=cwd, abort=abort, on_output=on_output)
	return finish_streaming(h, timeout_ms=timeout_ms)
