"""副作用工具的幂等动作账本。

动作账本解决的是断流/恢复边界，而不是替代 rewind。它只记录动作意图、状态
和有限结果预览，不保存完整参数、文件内容或秘密。默认关闭；benchmark 或
长任务宿主可通过 ``XEYO_ACTION_JOURNAL=1`` 开启。

状态语义：

``executing``
    意图已持久化，执行尚未得到终态。
``completed``
    执行已经得到结果；同一个 idempotency key 可安全 replay 有限结果。
``unknown``
    进程/abort 在执行边界中断，不能自动重做副作用。
``failed``
    工具返回了明确失败结果；允许上层在新的 tool call 中显式重试。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from session.persistence import default_sessions_dir, safe_session_filename

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
	key = str(path)
	with _LOCKS_GUARD:
		lock = _LOCKS.get(key)
		if lock is None:
			lock = threading.RLock()
			_LOCKS[key] = lock
		return lock


def enabled_from_env() -> bool:
	raw = os.environ.get("XEYO_ACTION_JOURNAL", "0").strip().lower()
	return raw in {"1", "true", "yes", "on"}


def action_identity(
	*, session_id: str, turn_id: str, tool_use_id: str, tool_name: str, tool_input: dict[str, Any]
) -> tuple[str, str]:
	"""返回稳定的 ``(action_id, idempotency_key)``；参数只进摘要 hash。"""
	try:
		payload = json.dumps(tool_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	except (TypeError, ValueError):
		payload = repr(tool_input)
	seed = "|".join((session_id, turn_id, tool_use_id, tool_name, payload))
	digest = hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()
	return f"act_{digest[:24]}", f"idem_{digest}"


@dataclass(frozen=True)
class ActionDecision:
	action: str
	record: dict[str, Any] | None = None


class ActionJournal:
	"""一个 session 的 append-only 动作状态账本。"""

	MAX_REPLAY_CHARS = 12_000

	def __init__(
		self,
		session_id: str,
		*,
		enabled: bool | None = None,
		sessions_dir: Path | None = None,
	) -> None:
		self.session_id = str(session_id or "").strip()
		if not self.session_id:
			raise ValueError("session_id is required")
		self.enabled = enabled_from_env() if enabled is None else bool(enabled)
		root = sessions_dir or default_sessions_dir()
		self.path = root / safe_session_filename(self.session_id) / "actions.jsonl"

	def _append(self, record: dict[str, Any]) -> None:
		if not self.enabled:
			return
		self.path.parent.mkdir(parents=True, exist_ok=True)
		line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
		with _lock_for(self.path):
			with self.path.open("a", encoding="utf-8", newline="") as handle:
				handle.write(line)
				handle.flush()
				if os.environ.get("XEYO_REWIND_FSYNC", "").strip().lower() in {"1", "true", "yes", "on"}:
					os.fsync(handle.fileno())

	def _latest(self) -> dict[str, dict[str, Any]]:
		if not self.enabled:
			return {}
		latest: dict[str, dict[str, Any]] = {}
		try:
			with self.path.open("r", encoding="utf-8") as handle:
				for line in handle:
					try:
						row = json.loads(line)
					except (TypeError, json.JSONDecodeError):
						continue
					if isinstance(row, dict) and row.get("action_id"):
						latest[str(row["action_id"])] = row
		except OSError:
			pass
		return latest

	def begin(
		self,
		*,
		action_id: str,
		idempotency_key: str,
		turn_id: str,
		tool_use_id: str,
		tool_name: str,
		side_effect: str,
	) -> ActionDecision:
		if not self.enabled:
			return ActionDecision("execute")
		# 读取 latest 与写入 executing 必须在同一把 session/action 锁内完成。
		# 否则两个并发恢复请求可能都先读到“无记录”，随后重复执行同一个副作用。
		with _lock_for(self.path):
			current = self._latest().get(action_id)
			if current is not None:
				status = str(current.get("status") or "")
				if status == "completed":
					return ActionDecision("replay", current)
				if status in {"executing", "unknown"}:
					return ActionDecision("recovery_required", current)
			now = time.time()
			self._append(
				{
					"action_id": action_id,
					"idempotency_key": idempotency_key,
					"session_id": self.session_id,
					"turn_id": turn_id,
					"tool_use_id": tool_use_id,
					"tool_name": tool_name,
					"side_effect": side_effect,
					"status": "executing",
					"created_at": now,
					"updated_at": now,
				}
			)
			return ActionDecision("execute")

	def complete(self, action_id: str, result: Any) -> None:
		if not self.enabled:
			return
		content = str(getattr(result, "content", "") or "")
		self._append(
			{
				"action_id": action_id,
				"status": "completed",
				"updated_at": time.time(),
				"result_content": content[: self.MAX_REPLAY_CHARS],
				"result_truncated": len(content) > self.MAX_REPLAY_CHARS,
				"result_is_error": bool(getattr(result, "is_error", False)),
				"result_status": str(getattr(result, "status", "") or ""),
				"error_kind": getattr(result, "error_kind", None),
				"retryable": bool(getattr(result, "retryable", False)),
				"side_effect": str(getattr(result, "side_effect", "unknown") or "unknown"),
			}
		)

	def unknown(self, action_id: str, error: str) -> None:
		if self.enabled:
			self._append(
				{
					"action_id": action_id,
					"status": "unknown",
					"updated_at": time.time(),
					"error": str(error)[:1000],
				}
			)

	def failed(self, action_id: str, result: Any) -> None:
		if self.enabled:
			self._append(
				{
					"action_id": action_id,
					"status": "failed",
					"updated_at": time.time(),
					"error": str(getattr(result, "content", "") or "")[:1000],
					"error_kind": getattr(result, "error_kind", None),
				}
			)

	def summary(self) -> dict[str, Any]:
		"""返回动作状态摘要，不返回参数、结果正文或秘密。"""
		latest = self._latest()
		counts: dict[str, int] = {}
		rows: list[dict[str, str]] = []
		for action_id, row in latest.items():
			status = str(row.get("status") or "unknown")
			counts[status] = counts.get(status, 0) + 1
			rows.append({"action_id": str(action_id), "status": status})
		rows.sort(key=lambda item: item["action_id"])
		return {"enabled": bool(self.enabled), "counts": counts, "actions": rows}


__all__ = ["ActionDecision", "ActionJournal", "action_identity", "enabled_from_env"]
