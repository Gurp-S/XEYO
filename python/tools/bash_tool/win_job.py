"""Windows Job Object：给 Bash 子进程树加内存上限，并在超时时整树杀掉。

非 Windows 或创建失败时静默降级为普通进程（仍走 taskkill /T）。
不做 AppContainer——会绊住本机 git/npm。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

# 默认 512 MiB；可用环境变量或 .xeyo-policy.json 覆盖。
DEFAULT_JOB_MEMORY_MB = 512


@dataclass
class JobHandle:
	"""持有 Job Object 句柄；close 时 KillOnJobClose 会杀仍在运行的成员。"""

	handle: Any = None

	def assign(self, pid: int) -> bool:
		if self.handle is None or os.name != "nt" or not pid:
			return False
		try:
			import ctypes
			from ctypes import wintypes

			kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
			PROCESS_SET_QUOTA = 0x0100
			PROCESS_TERMINATE = 0x0001
			PROCESS_ASSIGN = PROCESS_SET_QUOTA | PROCESS_TERMINATE
			OpenProcess = kernel32.OpenProcess
			OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
			OpenProcess.restype = wintypes.HANDLE
			AssignProcessToJobObject = kernel32.AssignProcessToJobObject
			AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
			AssignProcessToJobObject.restype = wintypes.BOOL
			CloseHandle = kernel32.CloseHandle

			proc = OpenProcess(PROCESS_ASSIGN, False, int(pid))
			if not proc:
				return False
			try:
				ok = bool(AssignProcessToJobObject(self.handle, proc))
			finally:
				CloseHandle(proc)
			return ok
		except Exception:  # noqa: BLE001
			return False

	def terminate(self) -> None:
		if self.handle is None or os.name != "nt":
			return
		try:
			import ctypes
			from ctypes import wintypes

			kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
			TerminateJobObject = kernel32.TerminateJobObject
			TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
			TerminateJobObject.restype = wintypes.BOOL
			TerminateJobObject(self.handle, 1)
		except Exception:  # noqa: BLE001
			pass

	def close(self) -> None:
		if self.handle is None or os.name != "nt":
			self.handle = None
			return
		try:
			import ctypes
			from ctypes import wintypes

			kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
			CloseHandle = kernel32.CloseHandle
			CloseHandle.argtypes = [wintypes.HANDLE]
			CloseHandle.restype = wintypes.BOOL
			CloseHandle(self.handle)
		except Exception:  # noqa: BLE001
			pass
		self.handle = None


def _memory_limit_bytes(memory_mb: int | None) -> int:
	mb = memory_mb
	if mb is None:
		env = os.environ.get("XEYO_BASH_JOB_MEMORY_MB", "").strip()
		try:
			mb = int(env) if env else DEFAULT_JOB_MEMORY_MB
		except ValueError:
			mb = DEFAULT_JOB_MEMORY_MB
	mb = max(64, int(mb))
	return mb * 1024 * 1024


def create_bash_job(*, memory_mb: int | None = None) -> JobHandle:
	"""创建带 KillOnJobClose + 进程内存上限的 Job；失败返回空句柄。"""
	if os.name != "nt" or sys.platform != "win32":
		return JobHandle()
	try:
		import ctypes
		from ctypes import wintypes

		kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

		JobObjectExtendedLimitInformation = 9
		JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
		JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
		JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200

		class IO_COUNTERS(ctypes.Structure):
			_fields_ = [
				("ReadOperationCount", ctypes.c_uint64),
				("WriteOperationCount", ctypes.c_uint64),
				("OtherOperationCount", ctypes.c_uint64),
				("ReadTransferCount", ctypes.c_uint64),
				("WriteTransferCount", ctypes.c_uint64),
				("OtherTransferCount", ctypes.c_uint64),
			]

		class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
			_fields_ = [
				("PerProcessUserTimeLimit", ctypes.c_int64),
				("PerJobUserTimeLimit", ctypes.c_int64),
				("LimitFlags", wintypes.DWORD),
				("MinimumWorkingSetSize", ctypes.c_size_t),
				("MaximumWorkingSetSize", ctypes.c_size_t),
				("ActiveProcessLimit", wintypes.DWORD),
				("Affinity", ctypes.c_size_t),
				("PriorityClass", wintypes.DWORD),
				("SchedulingClass", wintypes.DWORD),
			]

		class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
			_fields_ = [
				("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
				("IoInfo", IO_COUNTERS),
				("ProcessMemoryLimit", ctypes.c_size_t),
				("JobMemoryLimit", ctypes.c_size_t),
				("PeakProcessMemoryUsed", ctypes.c_size_t),
				("PeakJobMemoryUsed", ctypes.c_size_t),
			]

		CreateJobObjectW = kernel32.CreateJobObjectW
		CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
		CreateJobObjectW.restype = wintypes.HANDLE
		SetInformationJobObject = kernel32.SetInformationJobObject
		SetInformationJobObject.argtypes = [
			wintypes.HANDLE,
			ctypes.c_int,
			wintypes.LPVOID,
			wintypes.DWORD,
		]
		SetInformationJobObject.restype = wintypes.BOOL

		handle = CreateJobObjectW(None, None)
		if not handle:
			return JobHandle()

		info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
		limit = _memory_limit_bytes(memory_mb)
		info.BasicLimitInformation.LimitFlags = (
			JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
			| JOB_OBJECT_LIMIT_PROCESS_MEMORY
			| JOB_OBJECT_LIMIT_JOB_MEMORY
		)
		info.ProcessMemoryLimit = limit
		info.JobMemoryLimit = limit
		ok = SetInformationJobObject(
			handle,
			JobObjectExtendedLimitInformation,
			ctypes.byref(info),
			ctypes.sizeof(info),
		)
		if not ok:
			kernel32.CloseHandle(handle)
			return JobHandle()
		return JobHandle(handle=handle)
	except Exception:  # noqa: BLE001
		return JobHandle()
