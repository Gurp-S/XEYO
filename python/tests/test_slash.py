"""统一斜杠命令：registry manifest + dispatch 单测。"""

from __future__ import annotations

from pathlib import Path

import slash
from slash.dispatch import DispatchContext, dispatch
from slash.registry import COMMANDS, match_commands, parse_slash


# --------------------------------------------------------------------------- #
# registry / manifest
# --------------------------------------------------------------------------- #

def test_manifest_shape_and_alias_uniqueness() -> None:
	seen: set[str] = set()
	for c in COMMANDS:
		assert c.name and c.name == c.name.lower()
		assert c.usage.startswith("/")
		assert c.summary
		assert c.handler in ("client", "server")
		assert c.when in ("idle", "always")
		for a in c.aliases:
			assert a not in seen, f"alias conflict: {a}"
			seen.add(a)
	# 35 条命令、核心命令齐备
	assert len(COMMANDS) == 35
	names = {c.name for c in COMMANDS}
	for required in (
		"help", "version", "status", "usage", "context", "cwd", "clear",
		"transcript", "export", "retry", "mode", "output", "code", "model",
		"theme", "approval", "ls", "stop", "allow", "deny", "compact",
		"rule", "doctor", "proposals", "run", "git", "diff", "revert",
		"skills", "mcp", "plugins", "exit", "load", "docs", "goal",
	):
		assert required in names, f"missing command: {required}"


def test_parse_slash_basic_alias_and_unknown() -> None:
	c, a = parse_slash("/help")
	assert c is not None and c.name == "help" and a == ""
	c, a = parse_slash("/mode plan")
	assert c is not None and c.name == "mode" and a == "plan"
	c, a = parse_slash("/历史 5")
	assert c is not None and c.name == "transcript" and a == "5"
	c, a = parse_slash("/目录")
	assert c is not None and c.name == "cwd"
	c, a = parse_slash("/不存在 x")
	assert c is None and a == "不存在 x"
	c, a = parse_slash("普通消息 /help")
	assert c is None and a == ""
	c, a = parse_slash("/")
	assert c is None


def test_match_commands_prefix_and_surfaces() -> None:
	out = match_commands("c", surfaces=("gui",))
	names = {c.name for c in out}
	assert "clear" in names and "code" in names and "context" in names
	# /theme 只在 gui；/exit 不在 gui
	assert "theme" in {c.name for c in match_commands("", surfaces=("gui",))}
	assert "exit" not in {c.name for c in match_commands("", surfaces=("gui",))}
	assert "exit" in {c.name for c in match_commands("", surfaces=("cli",))}


def test_help_text_filters_and_groups() -> None:
	gui_help = slash.help_text(surfaces=("gui",))
	assert "/help" in gui_help and "/theme" in gui_help
	assert "/exit" not in gui_help
	cli_help = slash.help_text(surfaces=("cli",))
	assert "/exit" in cli_help and "/theme" not in cli_help
	assert "● " in cli_help  # 类别分组


def test_alias_conflict_guard() -> None:
	# registry 模块导入即代表无别名冲突；这里显式断言关键别名归属
	assert slash.get_command("/目录").name == "cwd"
	assert slash.get_command("/列目录").name == "ls"
	assert slash.get_command("/approve").name == "allow"
	assert slash.get_command("/reject").name == "deny"
	assert slash.get_command("/history").name == "transcript"
	assert slash.get_command("/压缩").name == "compact"


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #

def test_dispatch_unknown_and_client_commands() -> None:
	ctx = DispatchContext(session_id="s1", workspace="")
	r = dispatch("不存在", "", ctx=ctx)
	assert r.handled is False and r.kind == "unknown"
	r = dispatch("mode", "plan", ctx=ctx)
	assert r.handled is False  # client 命令不进 dispatcher


def test_dispatch_cwd_and_status() -> None:
	ctx = DispatchContext(session_id="s1", workspace="D:\\tmp-ws")
	r = dispatch("cwd", "", ctx=ctx)
	assert r.handled and r.kind == "info" and r.result["cwd"] == "D:\\tmp-ws"
	r = dispatch("status", "", ctx=ctx)
	assert r.handled and r.kind == "info"
	assert "工作区" in r.message


class _FakeWorking:
	def __init__(self) -> None:
		self.compact_cursor = 0
		self.c2_summary_text = ""
		self.todos: list = []


class _FakeMessages:
	def __init__(self, rows: list[dict]) -> None:
		self._rows = rows

	def as_api_messages(self) -> list[dict]:
		return self._rows


class _FakeSession:
	def __init__(self, rows: list[dict]) -> None:
		self.messages = _FakeMessages(rows)
		self.working = _FakeWorking()
		self.session_id = "fake"


class _FakeEngine:
	def __init__(self, rows: list[dict], cwd: str = "") -> None:
		self._session = _FakeSession(rows)
		self.config = {"cwd": cwd} if cwd else {}

	def interrupt(self) -> None:  # pragma: no cover
		pass


def test_dispatch_transcript_and_context_use_fake_engine() -> None:
	rows = [
		{"role": "user", "content": "帮我看看 main.py"},
		{"role": "assistant", "content": "好的，我先读文件。"},
	]
	ctx = DispatchContext(session_id="fake", engine=_FakeEngine(rows))
	r = dispatch("transcript", "2", ctx=ctx)
	assert r.handled and r.result["count"] == 2
	assert "[你]" in r.message and "[XEYO]" in r.message
	r = dispatch("ctx", "", ctx=ctx)
	assert r.handled and r.result["messages"] == 2
	r = dispatch("compact", "", ctx=ctx)
	assert r.handled and r.kind == "memory"


def test_dispatch_export_writes_within_workspace(tmp_path: Path) -> None:
	rows = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
	ctx = DispatchContext(session_id="fake", engine=_FakeEngine(rows), workspace=str(tmp_path))
	r = dispatch("export", "out", ctx=ctx)
	assert r.handled and r.result["ok"] is True
	written = Path(r.result["path"])
	assert written.exists() and written.parent == tmp_path.resolve()
	assert "hello" in written.read_text(encoding="utf-8")
	# 越界路径拒绝
	r = dispatch("export", "../escape.md", ctx=ctx)
	assert r.handled and r.result["ok"] is False


def test_dispatch_ls_lists_and_blocks_escape(tmp_path: Path) -> None:
	(tmp_path / "sub").mkdir()
	(tmp_path / "a.txt").write_text("x", encoding="utf-8")
	ctx = DispatchContext(session_id="fake", workspace=str(tmp_path))
	r = dispatch("ls", "", ctx=ctx)
	assert r.handled and "sub/" in r.message and "a.txt" in r.message
	r = dispatch("ls", "..", ctx=ctx)
	assert r.result["ok"] is False


def test_dispatch_allow_without_pending(tmp_path: Path) -> None:
	# 无挂起请求 → 友好提示而非异常
	ctx = DispatchContext(session_id="no-such-session", workspace=str(tmp_path))
	r = dispatch("allow", "", ctx=ctx)
	assert r.handled and r.kind == "control"
	assert "没有待确认" in r.message


def test_dispatch_git_without_repo_fails_gracefully(tmp_path: Path) -> None:
	ctx = DispatchContext(session_id="fake", workspace=str(tmp_path))
	r = dispatch("git", "status", ctx=ctx)
	assert r.handled and r.kind == "tool"
	# 非 git 目录 → 优雅失败信息，不抛异常
	assert r.result is not None


def test_dispatch_extension_disabled_by_default(tmp_path: Path) -> None:
	ctx = DispatchContext(session_id="fake", workspace=str(tmp_path))
	for cmd in ("skills", "mcp", "plugins"):
		r = dispatch(cmd, "", ctx=ctx)
		assert r.handled and r.kind == "extension", cmd


def test_dispatch_skills_menu_filters_user_invocable_false(tmp_path: Path) -> None:
	# F4（§2 决策 3）：/skills 菜单不展示 user_invocable:false；show 按名仍可查。
	import json

	skills = tmp_path / ".xeyo" / "skills"
	(skills / "pub").mkdir(parents=True)
	(skills / "pub" / "SKILL.md").write_text(
		"---\ndescription: 公开技能\n---\n# pub\n", encoding="utf-8"
	)
	(skills / "internal").mkdir(parents=True)
	(skills / "internal" / "SKILL.md").write_text(
		"---\ndescription: 内部技能\nuser_invocable: false\n---\n# internal\n",
		encoding="utf-8",
	)
	(tmp_path / ".xeyo" / "settings.json").write_text(
		json.dumps({"enabled_extensions": True}), encoding="utf-8"
	)
	ctx = DispatchContext(session_id="fake", workspace=str(tmp_path))
	r = dispatch("skills", "", ctx=ctx)
	assert r.handled and r.kind == "extension"
	assert "pub" in r.message
	assert "internal" not in r.message
	# 显式按名 show 是详情视图，不是菜单：不受过滤影响。
	r2 = dispatch("skills", "show internal", ctx=ctx)
	assert r2.handled and "internal" in r2.message
