"""filehelper 批准/拒绝命令与 pending 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from audit.log import default_audit_log, reset_default_audit_log
from channels.filehelper import SESSION_ID
from channels.filehelper.commands import help_text, parse_command
from permissions.store import default_permission_store


def test_help_lists_allow_deny() -> None:
	text = help_text()
	assert "/allow" in text
	assert "/deny" in text


def test_parse_command_allow_deny_filehelper() -> None:
	assert parse_command("/allow").name == "allow"  # type: ignore[union-attr]
	assert parse_command("允许").name == "allow"  # type: ignore[union-attr]
	assert parse_command("/deny").name == "deny"  # type: ignore[union-attr]


def test_filehelper_resolve_writes_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	reset_default_audit_log()
	monkeypatch.setenv("XEYO_AUDIT_LOG", str(tmp_path / "a.jsonl"))
	reset_default_audit_log()
	store = default_permission_store()
	item = store.create(
		session_id=SESSION_ID,
		turn_id="t1",
		tool_name="Bash",
		tool_input={"command": "python app.py"},
		reason="needs_confirmation",
		prompt="Allow executing: python app.py",
		matched_rule="bash_remote_ask",
		command_summary="python app.py",
	)
	assert store.resolve(item.request_id, True, actor="filehelper") is True
	rows = default_audit_log().read_all()
	resolved = [r for r in rows if r.get("kind") == "permission.resolved"]
	assert len(resolved) == 1
	assert resolved[0]["matched_rule"] == "bash_remote_ask"
	assert resolved[0]["approved"] is True
	assert resolved[0]["actor"] == "filehelper"
	assert resolved[0]["command_summary"] == "python app.py"
	reset_default_audit_log()
	monkeypatch.delenv("XEYO_AUDIT_LOG", raising=False)


def test_filehelper_service_wires_permission() -> None:
	import inspect

	from channels.filehelper import service as fh

	src = inspect.getsource(fh.start)
	assert "set_on_permission(on_permission)" in src
	assert 'name in {"allow", "deny"}' in src
