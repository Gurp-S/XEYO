# -*- coding: utf-8 -*-
"""文件系统探针：**按活动路由**回答 exists / isdir / size / mtime。

## 为什么需要单独一层

工具的路径预检散落在各文件里，直接调 ``os.path.*``。宿主上没问题；一旦工作面
在容器里（``XEYO_DOCKER_CONTAINER`` / ContextVar），这些预检会：

1. 把容器路径 ``/app/x`` 规范化成 ``D:\\app\\x``（Windows ``abspath`` 的产物）；
2. 然后回答"不存在 / 不是目录 / 拿不到大小"。

后果不是报错，而是**静默错答**：Read 说"文件不存在"、Edit 说"文件为空"、Write
以为在新建文件。模型据此改策略，而文件明明好好地在容器里。

本模块是 ``tools/container_fs.py`` 在**预检语义**上的薄封装：宿主路由逐字等价于
原 ``os.path`` 行为（含 ``errors`` 语义），容器路由问容器。所有文件工具的预检
都应走这里，不要再直接 import os.path。
"""

from __future__ import annotations

import os

__all__ = ["exists", "getsize", "isdir", "routed"]


def routed() -> str:
	"""活动容器 id；宿主路由返回空串。"""
	try:
		from tools.container_fs import active_container

		return active_container()
	except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
		return ""


def exists(path: str) -> bool:
	"""路径是否存在。宿主路由 = ``os.path.exists``（字节级同语义）。"""
	if routed():
		from tools.container_fs import exists as _cfs_exists

		return bool(_cfs_exists(path))
	try:
		return os.path.exists(path)
	except (OSError, ValueError):
		return False


def isdir(path: str) -> bool:
	"""是否为目录。"""
	if routed():
		from tools.container_fs import is_dir as _cfs_isdir

		return bool(_cfs_isdir(path))
	try:
		return os.path.isdir(path)
	except (OSError, ValueError):
		return False


def getsize(path: str) -> int:
	"""文件字节数；不可得时抛 ``OSError``（与 ``os.path.getsize`` 同契约）。"""
	if routed():
		from tools.container_fs import container_exec, to_container_path

		probed = container_exec(
			f"stat -c %s -- {_sq(to_container_path(path))} 2>/dev/null"
		)
		if probed is None or probed[0] != 0 or not probed[1].strip():
			raise OSError(f"cannot stat (container): {path}")
		try:
			return int(probed[1].strip().splitlines()[0])
		except (ValueError, IndexError) as exc:
			raise OSError(f"cannot stat (container): {path}") from exc
	return os.path.getsize(path)


def _sq(value: str) -> str:
	return "'" + str(value).replace("'", "'\"'\"'") + "'"
