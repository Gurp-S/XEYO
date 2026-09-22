"""权限裁决的机器身份。

权限结果仍由 ``policy.evaluate_policy`` 拥有；本模块只把当前会话、工作区、
审批模式和 live-mode revision 规整成一个不可猜的快照 id，供审计、挂起项和
runtime trace 关联。它不生成模型可见文案。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def permission_snapshot(
	*, session_id: str = "", cwd: str = "", mode: str = "", revision: int = 0
) -> dict[str, Any]:
	profile_id = ""
	try:
		from engine.workspace_context import get_execution_context

		ctx = get_execution_context()
		profile_id = str(getattr(ctx, "runtime_profile_id", "") or "")
		if not session_id and ctx is not None:
			session_id = str(ctx.session_id or "")
	except Exception:  # noqa: BLE001 — trace 旁路
		pass
	payload = {
		"session_id": str(session_id or ""),
		"cwd": str(cwd or ""),
		"mode": str(mode or ""),
		"revision": int(revision or 0),
		"runtime_profile_id": profile_id,
	}
	canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return {
		"snapshot_id": "perm:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32],
		**payload,
	}


def current_permission_snapshot(*, session_id: str = "", cwd: str = "") -> dict[str, Any]:
	"""读取当前 live permission 状态并生成快照身份。"""
	mode = ""
	revision = 0
	try:
		from permissions.policy import permission_mode

		mode = permission_mode()
	except Exception:  # noqa: BLE001
		pass
	try:
		from permissions.runtime_mode import get_runtime_mode_store

		row = get_runtime_mode_store().snapshot(str(session_id or ""))
		revision = int(row.get("revision") or 0)
	except Exception:  # noqa: BLE001
		pass
	return permission_snapshot(
		session_id=session_id, cwd=cwd, mode=mode, revision=revision
	)


def permission_decision_metadata(
	decision: Any,
	*,
	snapshot_id: str = "",
	resource: str = "",
) -> dict[str, str]:
	"""把策略结果规整成机器字段；不生成模型可见解释。"""
	reason = str(getattr(decision, "reason", "") or "")
	matched_rule = str(getattr(decision, "matched_rule", "") or "")
	reason_code = re.sub(r"[^A-Za-z0-9]+", "_", reason).strip("_").upper()
	return {
		"permission_action": str(getattr(getattr(decision, "decision", None), "value", "") or getattr(decision, "decision", "")),
		"permission_rule_id": matched_rule or (f"reason:{reason}" if reason else "policy:unknown"),
		"permission_reason_code": reason_code or "UNKNOWN",
		"permission_snapshot_id": str(snapshot_id or ""),
		"permission_resource": str(resource or ""),
	}


__all__ = [
	"current_permission_snapshot",
	"permission_decision_metadata",
	"permission_snapshot",
]
