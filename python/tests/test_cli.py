"""CLI unit tests (Typer CliRunner + fake model + v1.5 polish)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.attach_cmd import iter_sse_objects, parse_data_line
from cli.config_store import (
	load_config,
	resolve_base_url,
	validate_config_value,
)
from cli.interact import parse_permission_choice, prompt_permission
from cli.main import app
from cli.render import EventRenderer
from cli.sessions_cmd import format_updated_at
from cli.slash import handle_slash
from msgtypes.events import AssistantDelta, FinalEvent
from permissions.store import USER_CHOICE_DENY, default_permission_store
from session.workspace_path import python_package_root


runner = CliRunner()


def test_version() -> None:
	res = runner.invoke(app, ["version"])
	assert res.exit_code == 0
	assert "0.1.0" in res.stdout


def test_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	res = runner.invoke(app, ["config", "set", "provider", "openai"])
	assert res.exit_code == 0
	res = runner.invoke(app, ["config", "show"])
	assert res.exit_code == 0
	assert "provider=openai" in res.stdout
	res = runner.invoke(app, ["config", "path"])
	assert res.exit_code == 0
	assert "config.toml" in res.stdout


def test_config_set_rejects_bad_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	res = runner.invoke(app, ["config", "set", "provider", "nope"])
	assert res.exit_code == 2


def test_config_base_url_env_over_file(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	runner.invoke(app, ["config", "set", "base_url", "http://from-file"])
	cfg = load_config()
	assert cfg.base_url == "http://from-file"
	monkeypatch.setenv("XEYO_BASE_URL", "http://from-env")
	assert resolve_base_url(None, cfg=cfg) == "http://from-env"
	assert resolve_base_url("http://flag", cfg=cfg) == "http://flag"


def test_config_bad_toml_warns(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
	home = tmp_path / "home"
	home.mkdir()
	monkeypatch.setenv("XEYO_HOME", str(home))
	(home / "config.toml").write_text("[[[broken", encoding="utf-8")
	cfg = load_config()
	assert cfg.provider == "deepseek"
	err = capsys.readouterr().err
	assert "failed to parse" in err


def test_validate_permission_allow_maps_never() -> None:
	assert validate_config_value("permission_mode", "allow") == "never"


def test_validate_reasoning_tail() -> None:
	assert validate_config_value("reasoning_tail", "on") is True
	assert validate_config_value("reasoning_tail", "off") is False
	assert validate_config_value("reasoning_tail", "true") is True
	with pytest.raises(ValueError):
		validate_config_value("reasoning_tail", "maybe")


def test_chat_print_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_NO_SESSION_PERSISTENCE", "1")
	cwd = tmp_path / "ws"
	cwd.mkdir()
	res = runner.invoke(
		app,
		[
			"chat",
			"--provider",
			"fake",
			"--cwd",
			str(cwd),
			"--print",
			"--json",
			"hello",
		],
	)
	assert res.exit_code == 0, res.stdout + str(res.exception)
	lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
	assert lines
	parsed = [json.loads(ln) for ln in lines]
	types = {p.get("type") for p in parsed}
	assert "assistant_delta" in types or "result" in types or "final" in types


def test_chat_restored_messages(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	sessions = tmp_path / "sessions"
	sessions.mkdir()
	sid = "cli-hydrate-1"
	# hydrate 路径可接受的最小转录行。
	(sessions / f"{sid}.jsonl").write_text(
		json.dumps({"role": "user", "content": "prior", "id": "u1"}) + "\n",
		encoding="utf-8",
	)
	cwd = tmp_path / "ws"
	cwd.mkdir()
	res = runner.invoke(
		app,
		[
			"chat",
			"--provider",
			"fake",
			"--cwd",
			str(cwd),
			"--session",
			sid,
			"--print",
			"ping",
		],
	)
	assert res.exit_code == 0, str(res.exception)
	combined = (res.stdout or "") + (res.stderr or "")
	assert "restored 1" in combined


def test_cwd_guard_rejects_python_package() -> None:
	pkg = python_package_root()
	res = runner.invoke(
		app,
		["chat", "--provider", "fake", "--cwd", pkg, "--print", "x"],
	)
	assert res.exit_code != 0


def test_cwd_fallback_from_package_root(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	from cli.cwdutil import package_parent_workspace, resolve_cwd

	pkg = python_package_root()
	parent = package_parent_workspace()
	assert parent is not None
	monkeypatch.chdir(pkg)
	monkeypatch.delenv("XEYO_CWD", raising=False)
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	got = resolve_cwd(None, allow_package_fallback=True, persist=False)
	assert os.path.realpath(got) == os.path.realpath(parent)


def test_needs_credentials() -> None:
	from cli.setup_wizard import needs_credentials

	assert needs_credentials(provider="fake", api_key="") is False
	assert needs_credentials(provider="deepseek", api_key="sk") is False
	assert needs_credentials(provider="local", api_key="", base_url="http://x") is False
	assert needs_credentials(provider="deepseek", api_key="") is True


def test_setup_command_help() -> None:
	res = runner.invoke(app, ["setup", "--help"])
	assert res.exit_code == 0
	assert "setup" in (res.stdout or "").lower() or "API" in (res.stdout or "")


def test_root_help_mentions_bare_chat() -> None:
	res = runner.invoke(app, ["--help"])
	assert res.exit_code == 0
	out = res.stdout or ""
	assert "chat" in out.lower()


def test_logo_art_is_xeyo_mark() -> None:
	from cli.logo import LOGO_ART, LOGO_GLYPH

	assert "█" in LOGO_ART or "▀" in LOGO_ART
	assert LOGO_GLYPH
	# Lockup 必须声明身份才能渲染横幅。
	from rich.console import Console

	from cli.logo import logo_with_identity

	buf = Console(file=io.StringIO(), force_terminal=True, width=80, color_system=None)
	buf.print(logo_with_identity())
	text = buf.file.getvalue()  # type: ignore[union-attr]
	assert "XEYO" in text
	assert "I am XEYO" in text


def test_slash_help_and_modes() -> None:
	class _Eng:
		_session = None
		session_id = "cli-test"

	modes: list[str] = []

	r = handle_slash("/help", engine=_Eng(), set_agent_mode=modes.append)
	assert r.handled and r.message == ""  # /help 由 chat_cmd 渲染 help_panel

	r = handle_slash("/mode plan", engine=_Eng(), set_agent_mode=modes.append)
	assert r.handled and r.agent_mode == "plan" and modes == ["plan"]

	r = handle_slash("/ask", engine=_Eng(), set_agent_mode=modes.append)
	# /ask 不再是独立命令 → 统一报未知（主流 Agent 行为）
	assert r.handled and "未知命令" in r.message

	r = handle_slash("/clear", engine=_Eng(), set_agent_mode=modes.append)
	assert r.handled and r.rebuild_engine

	r = handle_slash("/exit", engine=_Eng(), set_agent_mode=modes.append)
	assert r.handled and r.exit_repl

	r = handle_slash("/压缩", engine=_Eng(), set_agent_mode=modes.append)
	assert r.handled and r.message  # server 命令走 dispatch（无会话也有降级文案）

	r = handle_slash("not a slash", engine=_Eng(), set_agent_mode=modes.append)
	assert not r.handled


@pytest.mark.asyncio
async def test_permission_fail_closed_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
	from cli.interact import resolve_permission_interactive
	from msgtypes.events import PermissionPendingEvent

	store = default_permission_store()
	item = store.create(
		session_id="cli-test",
		turn_id="t1",
		tool_name="Bash",
		tool_input={"command": "echo hi"},
		reason="needs_confirmation",
		prompt="Run?",
		matched_rule="bash_default_ask",
	)
	monkeypatch.setattr("cli.interact.is_tty", lambda: False)
	ev = PermissionPendingEvent(
		request_id=item.request_id,
		tool_name="Bash",
		tool_input={"command": "echo hi"},
		reason="needs_confirmation",
		prompt="Run?",
	)
	await resolve_permission_interactive(ev, json_mode=True)
	got = store.get(item.request_id)
	assert got is not None and got.resolved
	assert got.user_choice == USER_CHOICE_DENY or got.approved is False


def test_prompt_permission_headless_deny(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr("cli.interact.is_tty", lambda: False)
	d = prompt_permission(tool="Bash", prompt="run?", json_mode=False)
	assert d.choice == "deny" and d.headless


def test_parse_permission_choice() -> None:
	assert parse_permission_choice("a") == "allow"
	assert parse_permission_choice("remind") == "remind"
	assert parse_permission_choice("nope") == "deny"


def test_render_no_final_double_print(capsys: pytest.CaptureFixture[str]) -> None:
	r = EventRenderer(json_mode=False)
	r.emit(AssistantDelta(text="hello"))
	r.emit(FinalEvent(text="hello full duplicate"))
	out = capsys.readouterr().out
	assert "hello" in out
	assert "duplicate" not in out


def test_render_final_when_no_delta(capsys: pytest.CaptureFixture[str]) -> None:
	r = EventRenderer(json_mode=False)
	r.emit(FinalEvent(text="only final"))
	out = capsys.readouterr().out
	assert "only final" in out


def test_sse_parser_flushes_trailing_without_newline() -> None:
	chunks = ['data: {"n": 1}\n', 'data: {"n": 2}']
	objs = list(iter_sse_objects(iter(chunks)))
	assert objs == [{"n": 1}, {"n": 2}]
	assert parse_data_line('data: {"ok": true}\r') == {"ok": True}


def test_sessions_list_unreachable() -> None:
	res = runner.invoke(
		app,
		["sessions", "list", "--base-url", "http://127.0.0.1:9"],
	)
	assert res.exit_code == 1
	combined = (res.stdout or "") + (res.stderr or "")
	assert "xeyo serve" in combined or "failed" in combined


def test_format_updated_at_relative() -> None:
	import time

	ms = int(time.time() * 1000)
	text = format_updated_at(ms)
	assert "ago" in text or "just now" in text


def test_attach_permission_headless_via_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
	"""Attach path reuses prompt_permission fail-closed."""
	monkeypatch.setattr("cli.interact.is_tty", lambda: False)
	d = prompt_permission(tool="Write", prompt="?", force_headless=True)
	assert d.approved is False and d.choice == "deny"
