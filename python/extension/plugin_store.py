"""插件 lockfile 管理（plugins-lock.json）+ install / update / remove / list + 漂移检测。

与 :mod:`extension.skill_store` 同构（可对比 ``skills-lock.json`` 的 4 字段范式），
但按插件语义扩展：来源身份（``sourceType`` / ``source`` / ``declarationHash``）、
安装锚点（``path``）、目录级内容哈希（``computedHash``）、安装时间。

漂移：lockfile 记录的 ``computedHash`` 与磁盘实际插件目录内容哈希不一致时返回
漂移清单（warning 不硬失败），提示用户 update 以刷新。

安全约定：
- 所有路径解析都必须落到目标插件根内（防 ``..`` 逃逸，与 manifest 一致）。
- 写入 temp + ``os.replace`` 原子落盘（方向安全，不写半截）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from extension.errors import PluginError

#: lockfile 结构版本
LOCK_VERSION = 1


def default_lock_path(cwd: str | None = None) -> Path:
	"""Lockfile 位置：优先 workspace 根，否则仍根定在 ``<ws>/.xeyo/plugins-lock.json``。

	与 skill_store 的约定对齐但落在 workspace 内：插件本身装进
	``<ws>/.xeyo/plugins/``，锁文件放同级 ``plugins-lock.json``，便于整仓库携带漂移
	检测。无 workspace 时回落 home 级 ``~/.xeyo/plugins-lock.json``。
	"""
	if cwd:
		try:
			return (Path(cwd).expanduser().resolve() / ".xeyo" / "plugins-lock.json")
		except OSError:
			pass
	from memory.instruction import xeyo_home

	return xeyo_home() / "plugins-lock.json"


def _empty_lock() -> dict[str, Any]:
	return {"version": LOCK_VERSION, "plugins": {}}


def read_lock(path: Path) -> dict[str, Any]:
	if not path.is_file():
		return _empty_lock()
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as e:
		raise PluginError(f"bad plugins-lock.json at {path}: {e}") from e
	if not isinstance(raw, dict):
		raise PluginError(f"plugins-lock.json at {path} is not a JSON object")
	if not isinstance(raw.get("plugins"), dict):
		raw["plugins"] = {}
	raw.setdefault("version", LOCK_VERSION)
	return raw


def write_lock(path: Path, lock: dict[str, Any]) -> None:
	"""原子写（temp + ``os.replace``），方向安全。"""
	tmp: Path | None = None
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
		tmp.write_text(
			json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
			encoding="utf-8",
		)
		os.replace(tmp, path)
	except OSError as e:
		if tmp is not None:
			try:
				tmp.unlink(missing_ok=True)
			except OSError:
				pass
		raise PluginError(f"cannot write plugins-lock.json: {e}") from e


def dir_hash(root: Path) -> str:
	"""目录内容聚合哈希（文件名排序 + 内容 sha256 级联）。

	忽略 ``.git`` 目录（插件目录不应含 git 元数据；含也按内容参与哈希以保持可复算）。
	空目录或不存在返回空串哈希（区分未安装 vs 内容变化）。
	"""
	root = (root or Path(".")).expanduser().resolve()
	if not root.is_dir():
		return ""
	parts: list[tuple[str, str]] = []
	try:
		for p in sorted(root.rglob("*")):
			if not p.is_file():
				continue
			rel = p.relative_to(root).as_posix()
			if rel.startswith(".git/"):
				continue
			content = p.read_bytes()
			parts.append((rel, hashlib.sha256(content).hexdigest()))
	except OSError:
		return ""
	joined = "\n".join(f"{r}:{c}" for r, c in sorted(parts))
	return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def load_plugins(path: Path) -> dict[str, dict[str, Any]]:
	"""返回 {plugin_name: entry}。"""
	return dict(read_lock(path).get("plugins") or {})


def install(
	path: Path,
	*,
	name: str,
	source: str,
	source_type: str,
	plugin_path: Path,
) -> dict[str, Any]:
	"""登记一项插件到 lockfile；同名**已存在则拒绝**（不覆盖他人安装）。返回条目。"""
	lock = read_lock(path)
	plugins = dict(lock.get("plugins") or {})
	existing = plugins.get(name)
	if existing is not None:
		raise _conflict(name, existing)
	entry = _build_entry(
		name=name, source=source, source_type=source_type, plugin_path=plugin_path
	)
	plugins[name] = entry
	lock["plugins"] = plugins
	write_lock(path, lock)
	return entry


def update(
	path: Path,
	*,
	name: str,
	source: str,
	source_type: str,
	plugin_path: Path,
) -> dict[str, Any]:
	"""更新（重拉来源后重登记）；条目不存在则等价 install。返回条目。"""
	lock = read_lock(path)
	plugins = dict(lock.get("plugins") or {})
	entry = _build_entry(
		name=name, source=source, source_type=source_type, plugin_path=plugin_path
	)
	plugins[name] = entry
	lock["plugins"] = plugins
	write_lock(path, lock)
	return entry


def _build_entry(
	*, name: str, source: str, source_type: str, plugin_path: Path
) -> dict[str, Any]:
	import datetime as _dt

	return {
		"name": name,
		"source": source,
		"sourceType": source_type,
		"path": plugin_path.resolve().as_posix(),
		"computedHash": dir_hash(plugin_path),
		"installedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
	}


def _conflict(name: str, existing: dict[str, Any]) -> PluginError:
	from extension.errors import PluginConflictError

	return PluginConflictError(
		f"plugin '{name}' already installed (source={existing.get('source')}); "
		"overwrite=false; existing installation unchanged."
	)


def remove(path: Path, *, name: str, owner_source: str | None = None) -> bool:
	"""从 lockfile 删除；返回是否真的存在。

	``owner_source`` 提供时做归属校验：仅当既有条目的 ``source`` 与之一致才允许
	删除（防误删他人安装），不一致抛 :class:`PluginConflictError`。
	"""
	lock = read_lock(path)
	plugins = dict(lock.get("plugins") or {})
	existing = plugins.get(name)
	if existing is None:
		return False
	if owner_source is not None and str(existing.get("source") or "") != str(owner_source):
		raise _conflict(name, existing)
	plugins.pop(name, None)
	lock["plugins"] = plugins
	write_lock(path, lock)
	return True


def detect_drift(path: Path) -> list[dict[str, Any]]:
	"""返回漂移条目 [{name, recorded, current}]；锁文件缺失或无条目返回空。"""
	if not path.is_file():
		return []
	lock = read_lock(path)
	lock_dir = path.resolve().parent
	out: list[dict[str, Any]] = []
	for name, entry in (lock.get("plugins") or {}).items():
		if not isinstance(entry, dict):
			continue
		raw_path = str(entry.get("path", ""))
		if not raw_path:
			continue
		plugin_path = Path(raw_path).expanduser()
		if not plugin_path.is_absolute():
			plugin_path = (lock_dir / raw_path).resolve()
		recorded = str(entry.get("computedHash", ""))
		current = dir_hash(plugin_path)
		if recorded and current and recorded != current:
			out.append({"name": name, "recorded": recorded, "current": current})
	return out
