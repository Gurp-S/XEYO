"""Process liveness shared by engine and transport; standard library only."""
import ctypes
import os


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


