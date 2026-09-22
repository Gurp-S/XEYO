"""运行态 checkpoint 的最小持久化层。

checkpoint 只保存机器状态摘要，不保存 prompt、工具参数或秘密。它不尝试在
进程重启后自动重放副作用；执行中的 job/action 仍必须由 ActionJournal 和
JobRegistry 依据事实决定为 completed/failed/unknown。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from session.persistence import default_sessions_dir, safe_session_filename


def _enabled_from_env() -> bool:
	# 旁路形态：先显式开启验证收益，再并入默认主链路。
	raw = os.environ.get("XEYO_RUNTIME_CHECKPOINT", "0").strip().lower()
	return raw not in {"0", "false", "no", "off"}


class RuntimeCheckpointStore:
	VERSION = 1

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
		self.enabled = _enabled_from_env() if enabled is None else bool(enabled)
		root = sessions_dir or default_sessions_dir()
		self.path = root / safe_session_filename(self.session_id) / "runtime.json"

	def save(self, snapshot: dict[str, Any]) -> bool:
		if not self.enabled:
			return False
		payload = {
			"checkpoint_version": self.VERSION,
			"session_id": self.session_id,
			"saved_at": time.time(),
			"snapshot": snapshot,
		}
		self.path.parent.mkdir(parents=True, exist_ok=True)
		tmp = self.path.with_name(self.path.name + ".tmp")
		try:
			with tmp.open("w", encoding="utf-8", newline="") as handle:
				json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
				handle.flush()
				if os.environ.get("XEYO_REWIND_FSYNC", "").strip().lower() in {
					"1", "true", "yes", "on"
				}:
					os.fsync(handle.fileno())
			os.replace(tmp, self.path)
			return True
		except (OSError, TypeError, ValueError):
			try:
				tmp.unlink(missing_ok=True)
			except OSError:
				pass
			return False

	def load(self) -> dict[str, Any] | None:
		if not self.enabled:
			return None
		try:
			with self.path.open("r", encoding="utf-8") as handle:
				payload = json.load(handle)
		except (OSError, TypeError, json.JSONDecodeError):
			return None
		if not isinstance(payload, dict) or payload.get("checkpoint_version") != self.VERSION:
			return None
		snapshot = payload.get("snapshot")
		return dict(snapshot) if isinstance(snapshot, dict) else None


__all__ = ["RuntimeCheckpointStore"]
