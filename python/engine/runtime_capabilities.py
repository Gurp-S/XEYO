"""运行时能力预检。

预检只产生机器可读事实，不执行安装、网络探测或命令，不进入模型 prompt。
Docker/SSH 等非本地运行时不使用宿主 ``PATH`` 猜测能力，而是明确标记为
``None``（unknown），避免把宿主工具存在误报成容器工具存在。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Any, Literal

Capability = bool | None
RuntimeKind = Literal["local", "docker", "ssh", "unknown"]


def _which_any(names: tuple[str, ...]) -> bool:
	return any(bool(shutil.which(name)) for name in names)


@dataclass(frozen=True)
class RuntimeCapabilities:
	runtime: RuntimeKind
	cwd: str
	writable: Capability
	git: Capability
	python: Capability
	node: Capability
	compiler: Capability
	package_manager: Capability
	network: Capability = None
	disk_free_bytes: int | None = None
	container_id: str = ""
	checked_at: float = 0.0

	def to_dict(self) -> dict[str, Any]:
		return {
			"runtime": self.runtime,
			"cwd": self.cwd,
			"writable": self.writable,
			"git": self.git,
			"python": self.python,
			"node": self.node,
			"compiler": self.compiler,
			"package_manager": self.package_manager,
			"network": self.network,
			"disk_free_bytes": self.disk_free_bytes,
			"container_id": self.container_id,
			"checked_at": self.checked_at,
		}

	@property
	def capability_id(self) -> str:
		"""不含时间字段的稳定能力身份，用于 trace/恢复归因。"""
		payload = {
			key: value
			for key, value in self.to_dict().items()
			if key not in {"checked_at", "disk_free_bytes"}
		}
		encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
		return "cap:" + hashlib.sha256(encoded.encode("utf-8", "replace")).hexdigest()[:32]


def probe_runtime_capabilities(
	cwd: str,
	*,
	runtime: RuntimeKind = "local",
	container_id: str = "",
) -> RuntimeCapabilities:
	"""无副作用探测当前执行面的能力事实。"""
	root = os.path.abspath(os.path.expanduser(cwd or "."))
	now = time.time()
	if runtime != "local":
		return RuntimeCapabilities(
			runtime=runtime,
			cwd=root,
			writable=None,
			git=None,
			python=None,
			node=None,
			compiler=None,
			package_manager=None,
			network=None,
			container_id=str(container_id or ""),
			checked_at=now,
		)

	try:
		writable: Capability = os.path.isdir(root) and os.access(root, os.W_OK)
		disk_free = int(shutil.disk_usage(root).free) if os.path.isdir(root) else None
	except OSError:
		writable, disk_free = False, None
	python_available = bool(sys.executable) or _which_any(("python", "python3"))
	return RuntimeCapabilities(
		runtime="local",
		cwd=root,
		writable=writable,
		git=_which_any(("git",)),
		python=python_available,
		node=_which_any(("node",)),
		compiler=_which_any(("cc", "gcc", "clang", "cl")),
		package_manager=_which_any(("uv", "pip", "npm", "cargo")),
		network=None,
		disk_free_bytes=disk_free,
		container_id="",
		checked_at=now,
	)


__all__ = ["RuntimeCapabilities", "probe_runtime_capabilities"]
