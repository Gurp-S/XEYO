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
	"""
	# 安全硬化：--no-config 屏蔽宿主 RIPGREP_CONFIG_PATH / .rgrc 注入，保证装配的
	# argv 完全由本层控制（命令注入之外的配置注入风险，审计/可重现也受益）。
	if cmd and cmd[0] == "rg" and "--no-config" not in cmd:
		cmd = [cmd[0], "--no-config", *cmd[1:]]
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
