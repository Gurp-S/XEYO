"""Append-only JSONL 审计日志。

只记录最小事件集：
- permission.pending / permission.resolved / permission.denied
- tool.started / tool.finished

设计约束：append-only、每行一条 JSON、无内存索引；读取方（前端 ActivityLog
或未来查询 API）按需 tail 文件。写入线程安全（threading.Lock），跨进程不保证。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class AuditLog:
	def __init__(self, path: str | os.PathLike[str]) -> None:
		self._path = Path(path)
		self._lock = threading.Lock()

	@property
	def path(self) -> Path:
		return self._path

	def record(self, kind: str, **fields: Any) -> dict[str, Any]:
		"""追加一条审计事件；返回写入的条目（含 ts/kind）。"""
		from audit.redact import scrub_audit_fields

		safe = scrub_audit_fields(dict(fields))
		entry: dict[str, Any] = {
			"ts": round(time.time(), 3),
			"kind": kind,
			**safe,
		}
		line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
		with self._lock:
			self._path.parent.mkdir(parents=True, exist_ok=True)
			with self._path.open("a", encoding="utf-8", newline="") as handle:
				handle.write(line + "\n")
		return entry

	def read_all(self) -> list[dict[str, Any]]:
		"""读取全部条目（测试/诊断用；生产查询走 query）。"""
		if not self._path.is_file():
			return []
		rows: list[dict[str, Any]] = []
		with self._path.open("r", encoding="utf-8") as handle:
			for line in handle:
				line = line.strip()
				if not line:
					continue
				try:
					rows.append(json.loads(line))
				except json.JSONDecodeError:
					continue  # 坏行容忍：审计不能因单条损坏丢整体
		return rows

	def query(
		self,
		*,
		session_id: str | None = None,
		kind: str | None = None,
		since_ts: float | None = None,
		until_ts: float | None = None,
		limit: int = 100,
		offset: int = 0,
	) -> list[dict[str, Any]]:
		"""筛选审计事件；返回新→旧切片（limit/offset 基于筛选后全集）。

		kind 精确匹配，或以 ``.`` 结尾时按前缀匹配（如 ``permission.``）。
		"""
		limit = max(0, min(int(limit), 1000))
		offset = max(0, int(offset))
		sid = (session_id or "").strip() or None
		kind_raw = (kind or "").strip() or None
		prefix = bool(kind_raw and kind_raw.endswith("."))

		matched: list[dict[str, Any]] = []
		for row in self.read_all():
			if sid is not None and str(row.get("session_id") or "") != sid:
				continue
			if kind_raw is not None:
				k = str(row.get("kind") or "")
				if prefix:
					if not k.startswith(kind_raw):
						continue
				elif k != kind_raw:
					continue
			ts = row.get("ts")
			try:
				ts_f = float(ts) if ts is not None else None
			except (TypeError, ValueError):
				ts_f = None
			if since_ts is not None and (ts_f is None or ts_f < since_ts):
				continue
			if until_ts is not None and (ts_f is None or ts_f > until_ts):
				continue
			matched.append(row)

		matched.reverse()  # 新→旧
		if offset:
			matched = matched[offset:]
		if limit == 0:
			return []
		return matched[:limit]


_default: AuditLog | None = None
_default_lock = threading.Lock()


def default_audit_log() -> AuditLog:
	global _default
	with _default_lock:
		if _default is None:
			path = os.environ.get("XEYO_AUDIT_LOG", "").strip()
			if not path:
				from session.workspace_path import xeyo_data_root

				path = str(xeyo_data_root() / "audit" / "audit.jsonl")
			_default = AuditLog(path)
		return _default


def reset_default_audit_log() -> None:
	"""仅供测试注入临时路径后重置。"""
	global _default
	with _default_lock:
		_default = None
