"""工作区终端：在工作区根目录以平台默认 Shell 执行命令（一次性、超时、截断）。"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_DEFAULT_TIMEOUT_S = 30
_MAX_TIMEOUT_S = 120
_MAX_OUTPUT = 200_000


class TerminalError(RuntimeError):
	"""命令非法 / 无效参数。"""


def _decode(raw: bytes) -> str:
	if not raw:
		return ""
	for enc in ("utf-8", "gbk"):
		try:
			return raw.decode(enc)
		except UnicodeDecodeError:
			continue
	return raw.decode("utf-8", errors="replace")


def _shell_command(command: str) -> tuple[list[str], dict[str, str]]:
	if sys.platform == "win32":
		# PowerShell：别名/管道与界面“终端 · PowerShell”语义一致。
		env = os.environ.copy()
		env.setdefault("PYTHONIOENCODING", "utf-8")
		return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command], env
	return ["/bin/bash", "-lc", command], os.environ.copy()


def run_command(
	cwd: str,
	command: str,
	timeout_s: float = _DEFAULT_TIMEOUT_S,
	max_output: int = _MAX_OUTPUT,
) -> dict[str, Any]:
	root = Path(cwd).expanduser().resolve()
	if not root.is_dir():
		raise FileNotFoundError(f"workspace not found: {root}")
	command = (command or "").strip()
	if not command:
		raise TerminalError("command is empty")
	if len(command) > 4_000:
		raise TerminalError("command is too long")
	timeout = max(1.0, min(float(timeout_s), _MAX_TIMEOUT_S))
	argv, env = _shell_command(command)

	start = time.monotonic()
	timed_out = False
	exit_code: int | None = None
	stdout = ""
	stderr = ""
	try:
		proc = subprocess.run(
			argv,
			cwd=str(root),
			capture_output=True,
			timeout=timeout,
			env=env,
			check=False,
		)
		exit_code = proc.returncode
		stdout = _decode(proc.stdout)
		stderr = _decode(proc.stderr)
	except subprocess.TimeoutExpired as exc:
		timed_out = True
		if exc.stdout:
			stdout = _decode(exc.stdout)
		if exc.stderr:
			stderr = _decode(exc.stderr)
	except FileNotFoundError:
		raise TerminalError("shell not available")
	elapsed_ms = int((time.monotonic() - start) * 1000)

	truncated = {"stdout": len(stdout) > max_output, "stderr": len(stderr) > max_output}
	return {
		"ok": True,
		"cwd": str(root),
		"command": command,
		"shell": platform.system().lower() if sys.platform == "win32" else "bash",
		"exit_code": exit_code,
		"stdout": stdout[:max_output],
		"stderr": stderr[:max_output],
		"timed_out": timed_out,
		"truncated": truncated,
		"elapsed_ms": elapsed_ms,
	}
