"""诊断产物的落盘位置、原子写与磁盘配额。

产物都在 ``xeyo_data_root()/diagnostics/`` 下；audit / transcript / usage 仍是各
自的权威来源，本模块只写索引与捕获。写失败一律向上抛给调用方处理：诊断不得
吞掉主任务错误，也不得把没写成的实验标成成功。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

_STORE_LOCK = threading.RLock()

_DEFAULT_QUOTA_BYTES = 64 * 1024 * 1024

#: 回收 ``.tmp`` 残片前要先确认它不再被一次在飞的原子写持有（跨进程没有锁可用）。
_TMP_GRACE_S = 120.0


def diagnostics_root() -> Path:
	"""诊断产物根目录（可用 XEYO_DIAGNOSTICS_DIR 覆盖，供实验进程独立写入）。"""
	override = os.environ.get("XEYO_DIAGNOSTICS_DIR", "").strip()
	if override:
		return Path(override).expanduser()
	from session.workspace_path import xeyo_data_root

	return xeyo_data_root() / "diagnostics"


def runs_dir() -> Path:
	return diagnostics_root() / "runs"


def reports_dir() -> Path:
	return diagnostics_root() / "reports"


def captures_dir() -> Path:
	return diagnostics_root() / "captures"


def pins_dir() -> Path:
	return diagnostics_root() / "pins"


def baselines_dir() -> Path:
	return diagnostics_root() / "baselines"


def experiments_dir() -> Path:
	return diagnostics_root() / "experiments"


def reservations_path() -> Path:
	return diagnostics_root() / "reservations.jsonl"


_IDENT_MAX_LEN = 128


class InvalidIdentifier(ValueError):
	"""请求参数不像本模块生成的 id——拒绝拼接路径，不做静默清洗。"""


def safe_ident(value: object, *, label: str = "标识符") -> str:
	"""把外部传入的 id 收敛到 ``[A-Za-z0-9_.-]``；其余一律抛错。

	pin / report / experiment id 与 body_hash 都由本包自己生成（``pin_`` +
	16 hex 等），任何带分隔符、``..``、空白或 NUL 的取值都不可能是合法产物。
	诊断端点即便只听回环，也不得让请求参数决定文件落在哪里。
	"""
	text = str(value if value is not None else "")
	if not text or len(text) > _IDENT_MAX_LEN or text.strip() != text:
		raise InvalidIdentifier(f"{label}非法")
	if ".." in text:
		raise InvalidIdentifier(f"{label}非法")
	for ch in text:
		if (
			("a" <= ch <= "z")
			or ("A" <= ch <= "Z")
			or ("0" <= ch <= "9")
			or ch in "_-"
		):
			continue
		raise InvalidIdentifier(f"{label}非法")
	return text


def artifact_path(directory: Path, ident: str, *, suffix: str, label: str = "标识符") -> Path:
	"""``directory/<ident><suffix>`` 的唯一安全拼法。"""
	clean = safe_ident(ident, label=label)
	base = Path(directory)
	target = base / f"{clean}{suffix}"
	try:
		inside = target.resolve().is_relative_to(base.resolve())
	except OSError as exc:  # pragma: no cover — 解析失败按非法处理
		raise InvalidIdentifier(f"{label}非法") from exc
	if not inside:
		raise InvalidIdentifier(f"{label}越界")
	return target


def body_hash_path(directory: Path, body_hash: str) -> Path:
	"""捕获正文路径：只接受 64 位十六进制 sha256。"""
	clean = safe_ident(body_hash, label="body_hash")
	if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean.lower()):
		raise InvalidIdentifier("body_hash 非法")
	return artifact_path(
		Path(directory) / clean[:2], clean, suffix=".json.gz", label="body_hash"
	)


def quota_bytes() -> int:
	raw = os.environ.get("XEYO_DIAGNOSTICS_MAX_BYTES", "").strip()
	try:
		value = int(raw) if raw else _DEFAULT_QUOTA_BYTES
	except ValueError:
		value = _DEFAULT_QUOTA_BYTES
	return max(0, value)


def ensure_dirs() -> None:
	with _STORE_LOCK:
		for fn in (
			runs_dir,
			reports_dir,
			captures_dir,
			pins_dir,
			baselines_dir,
			experiments_dir,
		):
			fn().mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
	"""原子写 JSON（tmp + replace）。失败向上抛，由调用方决定是否阻断。"""
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + ".tmp")
	data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
	with _STORE_LOCK:
		with tmp.open("w", encoding="utf-8", newline="") as handle:
			handle.write(data + "\n")
		os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any] | None:
	"""读 JSON；缺失或损坏返回 None（缺项由上层记成 Gap，不臆造内容）。"""
	if not path.is_file():
		return None
	try:
		with path.open("r", encoding="utf-8") as handle:
			raw = json.load(handle)
	except (OSError, ValueError):
		return None
	return raw if isinstance(raw, dict) else None


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
	with _STORE_LOCK:
		with path.open("a", encoding="utf-8", newline="") as handle:
			handle.write(line + "\n")


def read_jsonl(path: Path, *, limit: int = 5000) -> list[dict[str, Any]]:
	"""读取 JSONL（旧→新）；坏行容忍，非 dict 行丢弃。"""
	if not path.is_file():
		return []
	rows: list[dict[str, Any]] = []
	with _STORE_LOCK:
		with path.open("r", encoding="utf-8", errors="replace") as handle:
			for line in handle:
				line = line.strip()
				if not line:
					continue
				try:
					row = json.loads(line)
				except ValueError:
					continue
				if isinstance(row, dict):
					rows.append(row)
	if limit > 0 and len(rows) > limit:
		return rows[-limit:]
	return rows


def dir_size(path: Path) -> int:
	if not path.is_dir():
		return 0
	total = 0
	for entry in path.rglob("*"):
		try:
			if entry.is_file():
				total += entry.stat().st_size
		except OSError:
			continue
	return total


def _pinned_markers() -> set[str]:
	"""被固定证据引用的文件不得被配额清理掉。"""
	out: set[str] = set()
	root = pins_dir()
	if not root.is_dir():
		return out
	for entry in root.rglob("*.json"):
		doc = read_json(entry) or {}
		for ref in doc.get("pinned_files") or []:
			if isinstance(ref, str) and ref:
				out.add(ref)
	return out


def enforce_quota(*, target: int | None = None) -> dict[str, Any]:
	"""按磁盘配额清理：跳过固定证据，按最旧优先删非固定产物。

	返回清理情况；固定证据不足空间时如实报告 ``shortfall``，不覆盖它们。
	"""
	cap = quota_bytes() if target is None else max(0, int(target))
	root = diagnostics_root()
	used = dir_size(root)
	result: dict[str, Any] = {
		"quota_bytes": cap,
		"used_bytes": used,
		"removed": 0,
		"freed_bytes": 0,
		"shortfall": 0,
	}
	if cap <= 0 or used <= cap:
		return result
	protected = _pinned_markers()
	# ``.tmp`` 永远不是权威产物（写入一律 tmp→replace），残片先回收。
	# 但回收要避开还在写的那一个：本模块的 _STORE_LOCK 只管本进程，GUI server 与
	# CLI 可以并发写同一目录，抢在 os.replace 之前 unlink 会让对方的原子写直接失败。
	now = time.time()
	for stale in root.rglob("*.tmp"):
		try:
			if stale.is_file():
				stat = stale.stat()
				if now - stat.st_mtime < _TMP_GRACE_S:
					continue
				size = stat.st_size
				stale.unlink()
				used -= size
				result["removed"] += 1
				result["freed_bytes"] += size
		except OSError:
			continue
	candidates: list[tuple[int, int, Path]] = []
	for entry in root.rglob("*"):
		try:
			if not entry.is_file():
				continue
			if str(entry) in protected:
				continue
			st = entry.stat()
			candidates.append((int(st.st_mtime), int(st.st_size), entry))
		except OSError:
			continue
	candidates.sort()
	for _mtime, size, entry in candidates:
		if used <= cap:
			break
		if entry.name.endswith(".tmp") and now - _mtime < _TMP_GRACE_S:
			# 这里也一样：候选清单会把在飞的 tmp 当普通文件删掉。
			continue
		try:
			entry.unlink()
		except OSError:
			continue
		used -= size
		result["removed"] += 1
		result["freed_bytes"] += size
	result["used_bytes"] = used
	if used > cap:
		result["shortfall"] = used - cap
	return result


_VERSION_CACHE: dict[str, Any] | None = None


def code_version(*, repo_root: str | None = None, timeout: float = 2.0) -> dict[str, Any]:
	"""**出这份报告的进程**所在树的版本：commit + 工作树是否干净。行号只是附加信息，不作主键。

	记录（审计 / 账本 / transcript）里不带版本字段，所以这个值不能读成"产生那些记录的引擎
	版本"：release 跑的是打包资源里的快照（见 gui/src-tauri/src/lib.rs 的 ``python_root``），
	与当前树可以差若干个提交。

	git 不可用时如实返回 ``unknown``，不谎报干净。
	"""
	global _VERSION_CACHE
	if _VERSION_CACHE is not None:
		return dict(_VERSION_CACHE)
	root = repo_root or str(Path(__file__).resolve().parents[1])
	info: dict[str, Any] = {
		"commit": "unknown",
		"branch": "unknown",
		"worktree_state": "unknown",
		"probed_at": round(time.time(), 3),
	}
	try:
		creation = 0x08000000 if os.name == "nt" else 0  # 不弹控制台窗口
		out = subprocess.run(  # noqa: S603 — 固定参数，无用户输入
			["git", "-C", root, "rev-parse", "--short=12", "HEAD"],
			capture_output=True,
			timeout=timeout,
			encoding="utf-8",
			errors="replace",
			creationflags=creation,
		)
		if out.returncode == 0 and out.stdout.strip():
			info["commit"] = out.stdout.strip()
		br = subprocess.run(  # noqa: S603
			["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
			capture_output=True,
			timeout=timeout,
			encoding="utf-8",
			errors="replace",
			creationflags=creation,
		)
		if br.returncode == 0 and br.stdout.strip():
			info["branch"] = br.stdout.strip()
		st = subprocess.run(  # noqa: S603
			["git", "-C", root, "status", "--porcelain"],
			capture_output=True,
			timeout=timeout,
			encoding="utf-8",
			errors="replace",
			creationflags=creation,
		)
		if st.returncode == 0:
			info["worktree_state"] = "dirty" if st.stdout.strip() else "clean"
		else:
			info["worktree_state"] = "unknown"
	except Exception:  # noqa: BLE001 — 版本探测不得影响诊断主流程
		pass
	_VERSION_CACHE = dict(info)
	return dict(info)


def reset_store_caches() -> None:
	"""仅供测试切换环境变量后重置进程内缓存。"""
	global _VERSION_CACHE
	with _STORE_LOCK:
		_VERSION_CACHE = None


__all__ = [
	"append_jsonl",
	"baselines_dir",
	"captures_dir",
	"code_version",
	"diagnostics_root",
	"dir_size",
	"enforce_quota",
	"ensure_dirs",
	"experiments_dir",
	"pins_dir",
	"quota_bytes",
	"read_json",
	"read_jsonl",
	"reports_dir",
	"reservations_path",
	"reset_store_caches",
	"runs_dir",
	"write_json",
]
