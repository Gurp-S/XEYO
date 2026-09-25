"""权限审计行必须带关联身份：诊断层靠它把审批与工具调用对上。

诊断层的夹具早就写着 ``tool_use_id``，而真实数据里 0/71 条 ``permission.pending``
与 0/107 条 ``permission.resolved`` 带这个字段（2026-09-25 尾窗实测）。引擎侧的接线
（``tools/tool_registry.py`` 把 ``tool_use.id`` 交给 coordinator）在 HEAD 里是完整的，
但**没有任何测试钉住"审计行要带这三项"** —— 链路一旦退回缺失，权限事件就只能按时间
顺序与调用近似对应（``rules.check_permission_block`` 的 coverage_gap 写的就是这种
降级），而诊断层仍然全绿。所以这条回归钉在写审计行的地方，不钉在读它的地方。
"""

from __future__ import annotations

import pytest

import audit.log as audit_mod
from audit.log import AuditLog, reset_default_audit_log
from engine.permission_coordinator import PermissionCoordinator
from engine.task_state import SessionTaskState
from permissions.store import PendingPermissionStore

#: 关联身份的取值刻意各不相同：写串了一个字段就该被发现。
_LINK = {"tool_use_id": "call_7", "model_request_id": "req_7", "projection_id": "proj_7"}


@pytest.fixture()
def audit_log(tmp_path):
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log  # 与 tests/test_audit_log.py 同法：注入默认实例
	yield log
	reset_default_audit_log()


def _by_kind(log: AuditLog) -> dict[str, dict]:
	return {str(row.get("kind")): row for row in log.read_all()}


def test_pending_row_carries_the_call_link(audit_log) -> None:
	coordinator = PermissionCoordinator(
		store=PendingPermissionStore(ttl_seconds=0),
		task_state=SessionTaskState("s1"),
		session_id="s1",
		turn_id="t1",
	)
	request_id = coordinator.request(
		tool_name="Bash",
		tool_input={"command": "echo hi"},
		reason="needs_confirmation",
		prompt="Allow?",
		**_LINK,
	)

	row = _by_kind(audit_log)["permission.pending"]
	assert row["request_id"] == request_id
	for key, value in _LINK.items():
		assert row.get(key) == value, f"permission.pending 丢了 {key}：审批将无法归到具体调用"


def test_resolved_row_carries_the_call_link(audit_log) -> None:
	"""桌面 resolve 走的是 store 自己的审计写入 —— 与 coordinator 那条不是一个函数。"""
	store = PendingPermissionStore(ttl_seconds=0)
	item = store.create(
		session_id="s1",
		turn_id="t1",
		tool_name="Bash",
		tool_input={"command": "echo hi"},
		reason="needs_confirmation",
		prompt="Allow?",
		**_LINK,
	)

	assert store.resolve(item.request_id, True, actor="desktop") is True

	row = _by_kind(audit_log)["permission.resolved"]
	assert row.get("approved") is True
	assert row.get("outcome") == "user_decided"
	for key, value in _LINK.items():
		assert row.get(key) == value, f"permission.resolved 丢了 {key}：裁决与调用断开"
