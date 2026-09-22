"""XEYO runtime 状态域与唯一写入权威。

事件流、trajectory 和 UI 都是派生/通知面；它们不能成为当前事实的第二个
写入源。本模块提供一个稳定的机器清单，供 runtime snapshot、checkpoint 和
诊断工具标明事实应回到哪里读取。
"""

from __future__ import annotations

from typing import Any


STATE_AUTHORITIES: dict[str, dict[str, Any]] = {
	"conversation": {"owner": "MessageStore", "derived": False},
	"workspace": {"owner": "WorkspaceRuntime/filesystem", "derived": False},
	"process": {"owner": "JobRegistry/ProcessManager", "derived": False},
	"permission": {"owner": "PermissionState", "derived": False},
	"projection": {"owner": "ProjectionCompiler", "derived": False},
	"lifecycle": {"owner": "AgentLifecycle/SessionTaskState", "derived": False},
	"trajectory": {"owner": "EventRecorder", "derived": True},
	"ui": {"owner": "runtime snapshot consumers", "derived": True},
	"events": {"owner": "notification only", "derived": True},
}


def authority_manifest() -> dict[str, dict[str, Any]]:
	"""返回防止调用方修改全局清单的副本。"""
	return {key: dict(value) for key, value in STATE_AUTHORITIES.items()}


__all__ = ["STATE_AUTHORITIES", "authority_manifest"]
