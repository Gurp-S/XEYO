"""XeyoUI 权限：按 action 分流（list 放行，其余 ASK；非法 DENY）。"""

from __future__ import annotations

from pathlib import Path

from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy


def _cwd(tmp_path: Path) -> str:
	(tmp_path / "note.txt").write_text("hi", encoding="utf-8")
	return str(tmp_path)


def test_list_sessions_allow(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy("XeyoUI", {"action": "list_sessions"}, cwd=cwd)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "ui_list_allow"


def test_open_preview_asks_inside(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	inside = str(tmp_path / "note.txt")
	r = evaluate_policy(
		"XeyoUI", {"action": "open_preview", "path": inside}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "ui_preview_ask"


def test_open_preview_outside_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	outside = str(tmp_path.parent / "secret.txt")
	r = evaluate_policy(
		"XeyoUI", {"action": "open_preview", "path": outside}, cwd=cwd
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_preview_outside_deny"


def test_open_preview_missing_path_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy("XeyoUI", {"action": "open_preview"}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_missing_path"


def test_open_panel_allows(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI", {"action": "open_panel", "panel": "git"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "ui_panel_allow"


def test_browser_nav_asks(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI",
		{"action": "browser", "url": "http://localhost:5173"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "ui_browser_ask"


def test_browser_op_allows(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI", {"action": "browser", "op": "reload"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "ui_browser_nav_allow"


def test_browser_bad_url_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI",
		{"action": "browser", "url": "javascript:alert(1)"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_browser_bad_url"


def test_browser_bad_op_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI", {"action": "browser", "op": "click"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_browser_bad_op"


def test_show_tool_flow_allows(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI", {"action": "show_tool_flow", "show": True}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "ui_tool_flow_allow"


def test_show_tool_flow_missing_show_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy("XeyoUI", {"action": "show_tool_flow"}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_missing_show"


def test_open_panel_invalid_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI", {"action": "open_panel", "panel": "settings"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_invalid_panel"


def test_send_to_session_asks(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI",
		{"action": "send_to_session", "session_id": "other", "text": "hi"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "ui_send_ask"


def test_send_to_session_side_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI",
		{"action": "send_to_session", "session_id": "side-1", "text": "hi"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_send_side_deny"


def test_send_to_session_missing_fields_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy(
		"XeyoUI",
		{"action": "send_to_session", "session_id": "other"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_send_missing_fields"


def test_unknown_action_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy("XeyoUI", {"action": "focus_session"}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_unknown_action"


def test_missing_action_deny(tmp_path: Path) -> None:
	cwd = _cwd(tmp_path)
	r = evaluate_policy("XeyoUI", {}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "ui_missing_action"
