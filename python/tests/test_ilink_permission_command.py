"""iLink 批准/拒绝命令与 pending_for_session 契约测试。"""

from __future__ import annotations

import pytest

from channels.filehelper.commands import parse_command
from channels.ilink.service import _run_command
from permissions.store import default_permission_store


def test_parse_command_allow_deny() -> None:
	assert parse_command("/allow").name == "allow"  # type: ignore[union-attr]
	assert parse_command("允许").name == "allow"  # type: ignore[union-attr]
	assert parse_command("/deny").name == "deny"  # type: ignore[union-attr]
	assert parse_command("拒绝").name == "deny"  # type: ignore[union-attr]


def test_pending_for_session_finds_and_resolves() -> None:
	store = default_permission_store()
	item = store.create(
		session_id="ilink:test-sess",
		turn_id="t1",
		tool_name="Write",
		tool_input={"file_path": "out.txt"},
		reason="needs_confirmation",
		prompt="Write to out.txt?",
	)
	assert store.pending_for_session("ilink:test-sess") is not None
	assert store.resolve(item.request_id, True, actor="ilink") is True
	assert store.pending_for_session("ilink:test-sess") is None


@pytest.mark.asyncio
async def test_run_command_allow_resolves_pending() -> None:
	sid = "ilink:test-allow"
	store = default_permission_store()
	item = store.create(
		session_id=sid,
		turn_id="t1",
		tool_name="Write",
		tool_input={"file_path": "out.txt"},
		reason="needs_confirmation",
		prompt="Write to out.txt?",
	)
	reply = await _run_command("allow", "允许", None, session_id=sid)  # type: ignore[arg-type]
	assert reply == "已允许，继续执行。"
	assert store.get(item.request_id) is not None
	assert store.get(item.request_id).resolved is True  # type: ignore[union-attr]
	assert store.get(item.request_id).approved is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_run_command_deny_resolves_pending() -> None:
	sid = "ilink:test-deny"
	store = default_permission_store()
	item = store.create(
		session_id=sid,
		turn_id="t1",
		tool_name="Write",
		tool_input={"file_path": "out.txt"},
		reason="needs_confirmation",
		prompt="Write to out.txt?",
	)
	reply = await _run_command("deny", "拒绝", None, session_id=sid)  # type: ignore[arg-type]
	assert reply == "已拒绝该操作。"
	assert store.get(item.request_id).approved is False  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_run_command_allow_no_pending() -> None:
	reply = await _run_command("allow", "允许", None, session_id="ilink:test-none")  # type: ignore[arg-type]
	assert reply == "当前没有待确认的操作"

