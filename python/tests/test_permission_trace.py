"""权限裁决快照身份契约。"""

from __future__ import annotations

from permissions.runtime_mode import RuntimeModeStore
from permissions.policy import PolicyDecision
from permissions.filesystem import PermissionDecision
from permissions.trace import permission_decision_metadata, permission_snapshot


def test_runtime_mode_revision_changes_snapshot_identity() -> None:
	store = RuntimeModeStore()
	store.begin_turn("s1", "risk")
	first = store.snapshot("s1")
	store.set("s1", "always")
	second = store.snapshot("s1")
	assert int(second["revision"]) > int(first["revision"])


def test_permission_snapshot_is_stable_for_same_inputs() -> None:
	a = permission_snapshot(session_id="s", cwd="/w", mode="risk", revision=2)
	b = permission_snapshot(session_id="s", cwd="/w", mode="risk", revision=2)
	assert a["snapshot_id"] == b["snapshot_id"]
	assert a["snapshot_id"].startswith("perm:")


def test_permission_decision_metadata_is_machine_explainable() -> None:
	decision = PolicyDecision(
		decision=PermissionDecision.DENY,
		reason="path outside working directory",
		matched_rule="path_scope_deny",
		path="C:/outside/file.txt",
	)
	fields = permission_decision_metadata(
		decision,
		snapshot_id="perm:1",
		resource=decision.path or "",
	)
	assert fields == {
		"permission_action": "deny",
		"permission_rule_id": "path_scope_deny",
		"permission_reason_code": "PATH_OUTSIDE_WORKING_DIRECTORY",
		"permission_snapshot_id": "perm:1",
		"permission_resource": "C:/outside/file.txt",
	}
