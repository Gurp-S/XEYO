"""ripgrep 子进程统一执行器（Grep / Glob 共用）。

对齐 ``tools/bash_tool/runner.py`` 的取消语义：
- abort 触发时杀死 rg 进程（watcher 线程轮询），避免停止后孤儿搜索继续烧 CPU；
- 超时同样杀进程，并把超时转成与原实现一致的 RuntimeError 文案；
- rg 缺失、exit >= 2 的错误文案保持不变（兼容既有测试/提示）。

被 abort 杀死的搜索按"无匹配（exit 1）"返回：外层 execute 随后的
``abort.raise_if_aborted()`` 会正常抛出 Aborted，由 query_loop 转成
StoppedEvent；不在此处抛错，避免双通道。
"""

from __future__ import annotations

import subprocess
import threading
import time

RG_POLL_INTERVAL_S = 0.05

#: 容器里没有 rg 时的专门文案：调用方据此回退 find/grep（任务镜像常年不带 rg）。
RG_MISSING_IN_CONTAINER = "ripgrep not available in the task container"


class RipgrepRunnerError(RuntimeError):
	"""rg 启动失败（缺失）或非零退出时抛出。"""


def _kill(proc: subprocess.Popen) -> None:
	if proc.poll() is not None:
		return
	try:
		proc.kill()
	except OSError:
		pass
	try:
		proc.wait(timeout=2)
	except Exception:  # noqa: BLE001 - 兜底，不让清理阻塞调用线程
		pass


def _run_in_container(
	cmd: list[str],
	*,
	cwd: str | None,
	timeout_seconds: float,
	timeout_message: str | None,
) -> list[str]:
	"""容器路由分支：同一条 argv 在**容器内**执行（2026-09-16 接线）。

	为什么必须在汇聚点接线：Grep / Glob / content_index 全走本函数，而它们的
	``cwd`` 在评测里是宿主**空** scratch 目录——不接线就统一报"没找到"，而文件
	明明在容器里（静默错答，比报错更坏）。

	约定与宿主分支一致：0=有匹配、1=无匹配、其它非零抛错；rg 在任务镜像里常年
	缺失（127）时抛专门文案，由调用方决定是否回退 find/grep。
	"""
	from tools.container_fs import run_argv

	probed = run_argv(list(cmd), cwd=cwd, timeout_s=max(1.0, float(timeout_seconds)))
	if probed is None:
		raise RipgrepRunnerError(
			"ripgrep runner: container route unavailable (the work面 is inside the container)"
		)
	code, out, err = probed
	if code == 127 or "command not found" in (err or ""):
		raise RipgrepRunnerError(RG_MISSING_IN_CONTAINER)
	if code >= 2:
		detail = (err or "").strip() or f"exit {code}"
		raise RipgrepRunnerError(f"ripgrep error: {detail}")
	return [
		line.replace("\r", "")
		for line in (out or "").splitlines()
		if line.strip()
	]


def run_ripgrep_lines(
	cmd: list[str],
	*,
	cwd: str | None = None,
	timeout_seconds: float,
	abort=None,
	timeout_message: str | None = None,
) -> list[str]:
	"""执行 argv 并返回按行拆分的 stdout（空行剔除）。

	约定退出码语义：0=有匹配，1=无匹配，>=2 抛错。abort 或超时杀死进程时，
	按现有文案路径处理超时；abort 杀死则视为无匹配返回。

	容器路由生效时改在容器内执行（见 ``_run_in_container``）；宿主路由行为不变。
	"""
	# 安全硬化：--no-config 屏蔽宿主 RIPGREP_CONFIG_PATH / .rgrc 注入，保证装配的
	# argv 完全由本层控制（命令注入之外的配置注入风险，审计/可重现也受益）。
	if cmd and cmd[0] == "rg" and "--no-config" not in cmd:
		cmd = [cmd[0], "--no-config", *cmd[1:]]
	try:
		from tools.container_fs import active_container

		_routed = active_container()
	except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
		_routed = ""
	if _routed:
		return _run_in_container(
			cmd, cwd=cwd, timeout_seconds=timeout_seconds, timeout_message=timeout_message
		)
	try:
		proc = subprocess.Popen(
			cmd,
			cwd=cwd,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			stdin=subprocess.DEVNULL,
			text=True,
			encoding="utf-8",
			errors="replace",
		)
	except FileNotFoundError as e:
		raise RipgrepRunnerError("tool running error,check ripgrep") from e
	except OSError as e:
		raise RipgrepRunnerError(f"failed to start ripgrep: {e}") from e

	killed_by_abort = False

	def _watch_abort() -> None:
		nonlocal killed_by_abort
		while proc.poll() is None:
			if abort is not None and getattr(abort, "aborted", False):
				killed_by_abort = True
				_kill(proc)
				return
			time.sleep(RG_POLL_INTERVAL_S)

	if abort is not None:
		threading.Thread(target=_watch_abort, daemon=True).start()

	timed_out = False
	out = ""
	err = ""
	try:
		out, err = proc.communicate(timeout=max(0.001, float(timeout_seconds)))
	except subprocess.TimeoutExpired:
		timed_out = True
		_kill(proc)
		try:
			out, err = proc.communicate(timeout=2)
		except Exception:  # noqa: BLE001
			out, err = "", ""
	finally:
		if proc.poll() is None:
			_kill(proc)

	if timed_out:
		message = timeout_message or (
			f"Ripgrep search timed out after {int(timeout_seconds)} seconds."
		)
		partial = (out or "").splitlines()
		if partial:
			message = message + "\nPartial output:\n" + "\n".join(partial[:200])
		raise RipgrepRunnerError(message)

	return_code = proc.returncode if proc.returncode is not None else 0
	if killed_by_abort or (abort is not None and getattr(abort, "aborted", False)):
		# 已中止：外层 raise_if_aborted 负责，这里按无匹配收敛。
		return []

	if return_code >= 2:
		detail = (err or "").strip() or f"exit {return_code}"
		raise RipgrepRunnerError(f"ripgrep error: {detail}")

	return [
		line.replace("\r", "")
		for line in (out or "").splitlines()
		if line.strip()
	]
