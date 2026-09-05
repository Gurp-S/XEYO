"""skill lockfile 管理（skills-lock.json）。

接管根目录已存在的 ``skills-lock.json``（4 字段：source / sourceType /
skillPath / computedHash），提供 install / update / remove / list + 启动漂移检测。

漂移：锁文件记录的 computedHash 与磁盘实际 SKILL.md 哈希不一致时返回漂移清单
（warning 不硬失败），提示用户 update 以刷新。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from extension.errors import ExtensionError

#: lockfile 结构版本
LOCK_VERSION = 1
_SKILL_URL_PREFIXES = ("http://", "https://", "github:")
_repo_cache: dict[str, Path] = {}


def default_lock_path(cwd: str | None = None) -> Path:
	"""Lockfile 位置：优先 workspace 根，否则 `~/.xeyo/skills-lock.json`。"""
	if cwd:
		try:
			return (Path(cwd).expanduser().resolve() / "skills-lock.json")
		except OSError:
			pass
	from memory.instruction import xeyo_home

	return xeyo_home() / "skills-lock.json"


def _empty_lock() -> dict[str, Any]:
	return {"version": LOCK_VERSION, "skills": {}}


def read_lock(path: Path) -> dict[str, Any]:
	if not path.is_file():
		return _empty_lock()
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as e:
		raise ExtensionError(f"bad skills-lock.json at {path}: {e}") from e
	if not isinstance(raw, dict):
		raise ExtensionError(f"skills-lock.json at {path} is not a JSON object")
	if not isinstance(raw.get("skills"), dict):
		raw["skills"] = {}
	raw.setdefault("version", LOCK_VERSION)
	return raw


def write_lock(path: Path, lock: dict[str, Any]) -> None:
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(
			json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
			encoding="utf-8",
		)
	except OSError as e:
		raise ExtensionError(f"cannot write skills-lock.json: {e}") from e


def _sha256_text(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_skill_file(skill_md: Path) -> str:
	"""SKILL.md 内容哈希（与 lockfile computedHash 一致）。"""
	try:
		return _sha256_text(skill_md.read_text(encoding="utf-8"))
	except OSError:
		return ""


def _resolve_skill_path(root: Path, skill_path: str) -> Path:
	"""把 lockfile 里的 skillPath（相对 plugins 根或绝对）解析到绝对路径。"""
	p = Path(skill_path).expanduser()
	if p.is_absolute():
		return p
	return (root / skill_path).resolve()


def load_skills(path: Path) -> dict[str, dict[str, Any]]:
	"""返回 {skill_name: {source, sourceType, skillPath, computedHash}}。"""
	return dict(read_lock(path).get("skills") or {})


def install(path: Path, *, name: str, source: str, source_type: str, skill_path: Path) -> dict[str, Any]:
	"""登记一项 skill 到 lockfile（沿用 4 字段）；已存在则覆盖。返回该条目。"""
	lock = read_lock(path)
	skills = dict(lock.get("skills") or {})
	entry = {
		"source": source,
		"sourceType": source_type,
		"skillPath": skill_path.as_posix(),
		"computedHash": hash_skill_file(skill_path),
	}
	skills[name] = entry
	lock["skills"] = skills
	write_lock(path, lock)
	return entry


def remove(path: Path, *, name: str) -> bool:
	"""从 lockfile 删除；返回是否真的存在。"""
	lock = read_lock(path)
	skills = dict(lock.get("skills") or {})
	existed = name in skills
	skills.pop(name, None)
	lock["skills"] = skills
	write_lock(path, lock)
	return existed


def detect_drift(path: Path) -> list[dict[str, Any]]:
	"""返回漂移条目 [{name, recorded, current}]；锁文件缺失或无条目返回空。"""
	if not path.is_file():
		return []
	lock = read_lock(path)
	roots = [Path(path).resolve().parent]  # 根目录；相对 skillPath 以根为基准
	out: list[dict[str, Any]] = []
	for name, entry in (lock.get("skills") or {}).items():
		if not isinstance(entry, dict):
			continue
		skill_path = _resolve_skill_path(roots[0], str(entry.get("skillPath", "")))
		recorded = str(entry.get("computedHash", ""))
		current = hash_skill_file(skill_path)
		if recorded and current and recorded != current:
			out.append({"name": name, "recorded": recorded, "current": current})
	return out
