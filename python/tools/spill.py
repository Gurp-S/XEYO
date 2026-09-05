"""T1 工具输出 spill：原始输出先落盘，截断只发生在模型可见投影。

设计（融合计划 T1/T27）：
- 固定顺序 ``raw → spill → compact/elide → 库``——spill 文件即「原始证据」，
  任意超预算输出都能事后取回原文（与 bash 自带的 truncate_for_model 同语义，
  registry 级 seam 覆盖其余工具）。
- 存储：``~/.xeyo/spill/<safe_session>/``（会话命名空间；可用
  ``XEYO_SPILL_DIR`` 覆盖）。``O_EXCL`` 独占创建，POSIX 下 0600。
- 保留纪律：save 时顺带清理超过 ``XEYO_SPILL_RETENTION_DAYS``（默认 7 天）
  的旧文件，防长期膨胀。
- spill 失败绝不抛给工具调用方——调用方原样返回未截断结果（宁可超预算，
  不可假证据）。
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ENV_SPILL_DIR = "XEYO_SPILL_DIR"
ENV_RETENTION_DAYS = "XEYO_SPILL_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 7

_SAFE_CHAR = re.compile(r"[A-Za-z0-9._-]")


@dataclass(frozen=True)
class SpillRef:
	"""一次 spill 的引用：文件路径 + 大小 + 给模型看的提示行。"""

	path: str
	bytes: int
	hint: str


def spill_root() -> Path:
	override = os.environ.get(ENV_SPILL_DIR, "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo" / "spill"


def _safe_session(session_id: str) -> str:
	raw = session_id or ""
	parts: list[str] = []
	for ch in raw:
		if ch == ":":
			parts.append("__")
		elif _SAFE_CHAR.match(ch):
			parts.append(ch)
		else:
			parts.append("_")
	name = "".join(parts).strip("._") or "session"
	return name[:120]


def _prune_old(root: Path, *, now: float | None = None) -> int:
	"""删除超过保留期的 spill 文件；返回删除数。尽力而为，不抛错。"""
	try:
		days = float(os.environ.get(ENV_RETENTION_DAYS, "").strip() or DEFAULT_RETENTION_DAYS)
	except ValueError:
		days = DEFAULT_RETENTION_DAYS
	if days <= 0:
		return 0
	cutoff = (now if now is not None else time.time()) - days * 86400.0
	removed = 0
	try:
		for dirpath, _dirnames, filenames in os.walk(root):
			for fn in filenames:
				p = Path(dirpath) / fn
				try:
					if p.stat().st_mtime < cutoff:
						p.unlink()
						removed += 1
				except OSError:
					continue
	except OSError:
		return removed
	return removed


def save_text(session_id: str, text: str) -> SpillRef:
	"""原始文本落盘；返回 SpillRef。失败抛 OSError（调用方兜底）。

	- ``O_EXCL`` 独占创建，绝不覆盖已有证据；
	- POSIX 追加 0600（Windows 忽略 mode，继承用户目录 ACL）；
	- 每次保存顺带做一次保留期清理（成本：一次 os.walk，量级可控）。
	"""
	data = (text or "").encode("utf-8", errors="replace")
	ns = spill_root() / _safe_session(session_id)
	ns.mkdir(parents=True, exist_ok=True)
	stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
	path = ns / f"{stamp}-{uuid.uuid4().hex[:8]}.txt"
	fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
	try:
		os.write(fd, data)
	finally:
		os.close(fd)
	# POSIX：open 的 mode 受 umask 影响，显式收紧一次。
	try:
		os.chmod(str(path), 0o600)
	except OSError:
		pass
	ref = SpillRef(
		path=str(path),
		bytes=len(data),
		hint=f"full output: {path} ({len(data)} bytes)",
	)
	try:
		_prune_old(spill_root())
	except Exception:  # noqa: BLE001 — 清理失败不影响保存
		pass
	return ref
