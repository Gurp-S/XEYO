"""T30 端口文件真相：``{port, pid, started_at, engine_version}``。

- 写入方：`server/__main__.py`（启动时落盘实际监听端口与进程身份）。
- 读取方：`gui/vite.config.ts`、`python/scripts/read_port.py`、
  `python/scripts/wait_health.py`、tui（JSON 优先，兼容旧「纯数字」格式）。
- 僵尸判定：port 文件里的 pid 不存在即清理文件；活实例保留，
  复用/拒绝由上层（lib.rs 健康探测 / 双实例提示）决定。
"""

from __future__ import annotations

import ctypes
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PORT_FILE_ENV = "XEYO_PORT_FILE"


def engine_version() -> str:
	"""引擎版本：port 文件与 /health 携带，供诊断与双实例判定。"""
	try:
		from cli import __version__

		return str(__version__)
	except Exception:
		return "0.0.0"


def default_port_file() -> Path:
	override = os.environ.get(PORT_FILE_ENV)
	if override:
		return Path(override)
	# __file__ 位于 <root>/python/server/portfile.py，parents[2] 即项目根
	return Path(__file__).resolve().parents[2] / ".xeyo" / "backend_port"


def is_pid_alive(pid: int) -> bool:
	"""进程是否存活（只探测，不下手杀）。"""
	pid = int(pid)
	if pid <= 0:
		return False
	if pid == os.getpid():
		return True
	if os.name == "nt":
		try:
			PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
			STILL_ACTIVE = 259
			ERROR_ACCESS_DENIED = 5
			kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
			handle = kernel32.OpenProcess(
				PROCESS_QUERY_LIMITED_INFORMATION, False, pid
			)
			if handle:
				code = ctypes.c_ulong()
				ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
				kernel32.CloseHandle(handle)
				if ok:
					# 句柄未释放的已终止进程 OpenProcess 仍成功：以退出码为准
					return int(code.value) == STILL_ACTIVE
				return True  # 打开成功但查询失败：保守视为存活
			return int(kernel32.GetLastError()) == ERROR_ACCESS_DENIED
		except Exception:
			return False
	try:
		os.kill(pid, 0)
		return True
	except ProcessLookupError:
		return False
	except PermissionError:
		return True  # 存在但无权发信号
	except OSError:
		return False


def write_port_file(port: int, path: Path | None = None) -> Path | None:
	"""写 {port, pid, started_at, engine_version}；尽力而为，失败不阻塞启动。"""
	target = path or default_port_file()
	payload = {
		"port": int(port),
		"pid": os.getpid(),
		"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
		"engine_version": engine_version(),
	}
	try:
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_text(json.dumps(payload), encoding="utf-8")
		return target
	except OSError:
		return None


def read_port_file(path: Path | None = None) -> dict | None:
	"""读端口文件：JSON 优先，兼容旧「纯数字」格式（旧格式无 pid）。"""
	target = path or default_port_file()
	try:
		raw = target.read_text(encoding="utf-8").strip()
	except OSError:
		return None
	if not raw:
		return None
	if raw.startswith("{"):
		try:
			data = json.loads(raw)
		except json.JSONDecodeError:
			return None
		if isinstance(data, dict) and isinstance(data.get("port"), int):
			return data
		return None
	try:
		return {"port": int(raw)}
	except ValueError:
		return None


def cleanup_stale_port_file(path: Path | None = None) -> bool:
	"""僵尸判定：pid 不存在即删文件。返回是否清理了僵尸文件。"""
	target = path or default_port_file()
	data = read_port_file(target)
	if data is None:
		return False
	pid = data.get("pid")
	if not isinstance(pid, int) or is_pid_alive(pid):
		return False
	try:
		target.unlink(missing_ok=True)
		return True
	except OSError:
		return False
