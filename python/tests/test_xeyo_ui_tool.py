"""XeyoUI 工具 execute 边界与 ui 旁路载荷。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from engine.abort import AbortController
from tools.xeyo_ui_tool import XeyoUITool


def _run(coro):
	return asyncio.run(coro)


def test_open_preview_requires_path(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(tool.execute({"action": "open_preview"}, abort))
	assert result.is_error
	assert "path" in result.content.lower()


def test_open_preview_success_ui(tmp_path: Path) -> None:
	f = tmp_path / "a.py"
	f.write_text("print(1)\n", encoding="utf-8")
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute({"action": "open_preview", "path": str(f)}, abort)
	)
	assert not result.is_error
	assert result.ui is not None
	assert result.ui["action"] == "open_preview"
	assert Path(result.ui["path"]).resolve() == f.resolve()


def test_open_panel_success_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute({"action": "open_panel", "panel": "terminal"}, abort)
	)
	assert not result.is_error
	assert result.ui == {"action": "open_panel", "panel": "terminal"}


def test_browser_nav_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute(
			{"action": "browser", "url": "http://localhost:5173"},
			abort,
		)
	)
	assert not result.is_error
	assert result.ui == {
		"action": "browser",
		"url": "http://localhost:5173",
	}
	assert result.content == "browser http://localhost:5173"


def test_browser_op_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(tool.execute({"action": "browser", "op": "reload"}, abort))
	assert not result.is_error
	assert result.ui == {"action": "browser", "op": "reload"}


def test_browser_open_only(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(tool.execute({"action": "browser"}, abort))
	assert not result.is_error
	assert result.ui == {"action": "browser"}


def test_browser_bad_url(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute({"action": "browser", "url": "javascript:alert(1)"}, abort)
	)
	assert result.is_error


def test_browser_bad_op(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(tool.execute({"action": "browser", "op": "click"}, abort))
	assert result.is_error


def test_open_panel_invalid(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute({"action": "open_panel", "panel": "settings"}, abort)
	)
	assert result.is_error


def test_show_tool_flow_success_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute({"action": "show_tool_flow", "show": True}, abort)
	)
	assert not result.is_error
	assert result.ui == {"action": "show_tool_flow", "show": True}


def test_show_tool_flow_hide_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(
		tool.execute({"action": "show_tool_flow", "show": False}, abort)
	)
	assert not result.is_error
	assert result.ui == {"action": "show_tool_flow", "show": False}


def test_show_tool_flow_requires_show(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(tool.execute({"action": "show_tool_flow"}, abort))
	assert result.is_error
	assert "show" in result.content.lower()


def test_send_to_session_self_deny(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	tool.set_session_id("sess-a")
	abort = AbortController()
	result = _run(
		tool.execute(
			{
				"action": "send_to_session",
				"session_id": "sess-a",
				"text": "hello",
			},
			abort,
		)
	)
	assert result.is_error
	assert "current" in result.content.lower()


def test_send_to_session_success_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	tool.set_session_id("sess-a")
	abort = AbortController()
	result = _run(
		tool.execute(
			{
				"action": "send_to_session",
				"session_id": "sess-b",
				"text": "ping",
			},
			abort,
		)
	)
	assert not result.is_error
	assert result.ui == {
		"action": "send_to_session",
		"session_id": "sess-b",
		"text": "ping",
	}


def test_list_sessions_no_ui(tmp_path: Path) -> None:
	tool = XeyoUITool(cwd=str(tmp_path))
	abort = AbortController()
	result = _run(tool.execute({"action": "list_sessions"}, abort))
	assert not result.is_error
	assert result.ui is None


def test_ui_actions_need_gui_on_cli_surface(tmp_path: Path) -> None:
	"""T35：非 GUI 面（cli 等）的 UI 副作用动作明确返回「需要 GUI」，不假成功。"""
	from permissions.policy import current_surface, set_surface

	prev = current_surface()
	try:
		set_surface("cli")
		tool = XeyoUITool(cwd=str(tmp_path))
		abort = AbortController()
		for action in ("open_preview", "open_panel", "browser"):
			payload: dict = {"action": action}
			if action == "open_preview":
				payload["path"] = str(tmp_path / "a.py")
			elif action == "open_panel":
				payload["panel"] = "terminal"
			result = _run(tool.execute(payload, abort))
			assert result.is_error
			assert "需要 GUI" in result.content
			assert "gui" in result.content.lower()
			assert result.ui is None
	finally:
		set_surface(prev)


def test_list_sessions_ok_on_cli_surface(tmp_path: Path) -> None:
	"""T35：list_sessions 是只读列举，任何面仍放行。"""
	from permissions.policy import current_surface, set_surface

	prev = current_surface()
	try:
		set_surface("cli")
		tool = XeyoUITool(cwd=str(tmp_path))
		abort = AbortController()
		result = _run(tool.execute({"action": "list_sessions"}, abort))
		assert not result.is_error
	finally:
		set_surface(prev)
