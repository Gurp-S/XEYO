"""记录进程启动时的源码修订，并与磁盘上的当前状态比较。

扫描由服务启动时的 ``log_loaded`` 显式触发，导入模块时不扫描目录。
结果仅写入面向用户的日志，不进入模型上下文。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from common.revision_probe import git_revision as _git_rev

_log = logging.getLogger("xeyo.revision")

#: 会随"改代码"漂移的目录（提示面 / 工具面 / 引擎 / 记忆面）。
WATCH_DIRS: tuple[str, ...] = ("prompt", "tools", "engine", "memory")

_PY_ROOT = Path(__file__).resolve().parents[1]

#: 启动时那一次快照；只在 :func:`log_loaded` 里填。
_STARTUP: dict[str, float | str] | None = None


def _newest_mtime(root: Path, name: str) -> float:
	base = root / name
	if not base.is_dir():
		return 0.0
	newest = 0.0
	for path in base.rglob("*.py"):
		try:
			newest = max(newest, path.stat().st_mtime)
		except OSError:
			continue
	return newest


def snapshot(root: Path | str | None = None) -> dict[str, float | str]:
	"""当前磁盘上的修订事实：git rev + 各目录最新 mtime。"""
	base = Path(root) if root else _PY_ROOT
	out: dict[str, float | str] = {"repo_rev": _git_rev(base), "rev_at": time.time()}
	for name in WATCH_DIRS:
		out[f"{name}_mtime"] = _newest_mtime(base, name)
	return out


def _fmt(ts: float | str) -> str:
	value = float(ts or 0)
	return time.strftime("%H:%M:%S", time.localtime(value)) if value else "-"


def log_loaded(root: Path | str | None = None) -> dict[str, float | str]:
	"""记录进程启动时的源码版本，供用户判断是否需要重启。

	同时写入标准输出，确保日志级别高于 INFO 时仍能看到启动版本。
	"""
	global _STARTUP
	_STARTUP = snapshot(root)
	line = "source revision: rev={} {}".format(
		_STARTUP.get("repo_rev") or "-",
		" ".join(f"{name}={_fmt(_STARTUP.get(f'{name}_mtime', 0.0))}" for name in WATCH_DIRS),
	)
	_log.info(line)
	try:
		print(f"[xeyo] {line}", flush=True)
	except Exception:  # noqa: BLE001 — 打不出来也不影响启动
		pass
	return _STARTUP


def stale_dirs(root: Path | str | None = None) -> tuple[str, ...]:
	"""相对启动快照，磁盘上已变动的目录（没调用过 :func:`log_loaded` ⇒ 空）。"""
	if _STARTUP is None:
		return ()
	now = snapshot(root)
	return tuple(
		name
		for name in WATCH_DIRS
		if float(now.get(f"{name}_mtime", 0.0))
		> float(_STARTUP.get(f"{name}_mtime", 0.0))
	)
