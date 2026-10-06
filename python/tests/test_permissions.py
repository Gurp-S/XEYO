"""权限沙箱 P0 测试。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.abort import AbortController
from engine.workspace_context import WorkspaceContext, set_workspace_context
from msgtypes.message import ToolUse
from permissions.filesystem import (
	PermissionDecision,
	check_read_permission_for_path,
	check_write_permission_for_path,
	default_permission_context,
	expand_to_abs,
	is_dangerous_path,
	path_in_allowed_working_path,
)
from permissions.gate import can_use_tool
from tools.catalog import build_default_registry
from tools.echo import EchoTool
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.tool_registry import ToolRegistry


@pytest.fixture
def work(tmp_path: Path) -> Path:
	(tmp_path / "safe.txt").write_text("hello", encoding="utf-8")
	(tmp_path / "python").mkdir()
	(tmp_path / "python" / "engine").mkdir()
	(tmp_path / "python" / "engine" / "query_loop.py").write_text(
		"# ok\n", encoding="utf-8"
	)
	git = tmp_path / ".git"
	git.mkdir()
	(git / "config").write_text("secret", encoding="utf-8")
	return tmp_path


def test_path_inside_cwd(work: Path) -> None:
	cwd = str(work)
	assert path_in_allowed_working_path(
		str(work / "python" / "engine" / "query_loop.py"), cwd=cwd
	)
	assert path_in_allowed_working_path("safe.txt", cwd=cwd)


def test_path_outside_cwd(work: Path) -> None:
	cwd = str(work)
	outside = os.path.abspath(os.sep + "Windows")
	# 非 Windows CI 上可能不同；仍必须在 work 之外。
	if path_in_allowed_working_path(outside, cwd=cwd):
		outside = str(work.parent / "other_secret.txt")
	assert not path_in_allowed_working_path(outside, cwd=cwd)


def test_windows_absolute_path_is_not_reinterpreted_as_relative(work: Path) -> None:
	cwd = str(work)
	path = expand_to_abs(r"C:\Temp\x", cwd=cwd)
	assert not path_in_allowed_working_path(path, cwd=cwd)


def test_dotdot_escape_denied(work: Path) -> None:
	cwd = str(work / "python")
	# 解析到 work 的父目录 — 应在 python/ 之外
	escaped = expand_to_abs("../safe.txt", cwd=cwd)
	# 从 python/ 的 ../safe.txt 落在 work/ — 若 cwd 为 python 仍在 work 内
	# 逃出 work 之上：
	escaped2 = expand_to_abs("../../outside.txt", cwd=cwd)
	assert not path_in_allowed_working_path(escaped2, cwd=cwd)


def test_dangerous_git_path(work: Path) -> None:
	cwd = str(work)
	git_cfg = str(work / ".git" / "config")
	assert is_dangerous_path(git_cfg, cwd=cwd)
	# 读侧：危险路径不再 ASK（只读确认对人不含信息）。
	d = check_read_permission_for_path(
		git_cfg, context=default_permission_context(cwd)
	)
	assert d == PermissionDecision.ALLOW
	# 写侧同一路径仍按危险路径 ASK/DENY，放宽不外溢。
	dw = check_write_permission_for_path(
		git_cfg, context=default_permission_context(cwd)
	)
	assert dw != PermissionDecision.ALLOW


def test_gate_allow_read_inside(work: Path) -> None:
	cwd = str(work)
	r = can_use_tool(
		"Read",
		{"file_path": str(work / "safe.txt")},
		cwd=cwd,
	)
	assert r.allowed
	assert r.reason in ("allowed", "inside_cwd")


def test_gate_deny_outside(work: Path) -> None:
	cwd = str(work)
	outside = str(work.parent / "not_in_workspace.txt")
	r = can_use_tool("Read", {"file_path": outside}, cwd=cwd)
	assert not r.allowed
	assert r.reason == "path_outside_working_directory"


def test_gate_allows_git_read_but_still_denies_git_write(work: Path) -> None:
	cwd = str(work)
	r = can_use_tool(
		"Read",
		{"file_path": str(work / ".git" / "config")},
		cwd=cwd,
	)
	assert r.allowed
	w = can_use_tool(
		"Write",
		{"file_path": str(work / ".git" / "config"), "content": "x"},
		cwd=cwd,
	)
	assert not w.allowed
	assert w.reason == "protected_metadata"


def test_current_session_spill_is_readable_but_other_session_is_not(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	from tools.spill import save_text

	spill_root = tmp_path / "spill"
	monkeypatch.setenv("XEYO_SPILL_DIR", str(spill_root))
	workspace = tmp_path / "workspace"
	workspace.mkdir()
	set_workspace_context(WorkspaceContext(session_id="session-a", cwd=str(workspace)))
	try:
		own = save_text("session-a", "own evidence")
		other = save_text("session-b", "other evidence")
		ctx = default_permission_context(str(workspace))
		assert check_read_permission_for_path(own.path, context=ctx) == PermissionDecision.ALLOW
		# 别的会话仍 DENY：区外读只在该目录"能一格记住"时才走 ASK，而 spill 根属于
		# 引擎自己的数据根（记住会把所有会话的溢出开成门）→ 维持硬 DENY。
		assert check_read_permission_for_path(other.path, context=ctx) == PermissionDecision.DENY
		from permissions.store import read_dir_fingerprint

		assert read_dir_fingerprint(other.path) == ""
	finally:
		set_workspace_context(None)


def test_gate_glob_default_cwd_ok(work: Path) -> None:
	r = can_use_tool("Glob", {"pattern": "**/*.py"}, cwd=str(work))
	assert r.allowed


def test_gate_glob_outside_path_denied(work: Path) -> None:
	outside = str(work.parent)
	r = can_use_tool(
		"Glob", {"pattern": "**/*", "path": outside}, cwd=str(work)
	)
	assert not r.allowed


def test_gate_todo_and_echo_allow(work: Path) -> None:
	cwd = str(work)
	assert can_use_tool("TodoWrite", {"todos": []}, cwd=cwd).allowed
	assert can_use_tool("echo", {"text": "hi"}, cwd=cwd).allowed
	# 缺省 bash=default：echo 只读命令自动放行。
	assert can_use_tool("Bash", {"command": "echo hi"}, cwd=cwd).allowed
	# 外发工具：policy ASK → 二元 gate DENY（需 UI 挂起，不是静默放行）
	assert not can_use_tool("Screenshot", {}, cwd=cwd).allowed
	inside = str(work / "out.png")
	assert not can_use_tool("SendToWeChat", {"path": inside}, cwd=cwd).allowed
	outside = str(work.parent / "secret.bin")
	assert not can_use_tool("SendToWeChat", {"path": outside}, cwd=cwd).allowed


def test_gate_bash_denies_destructive_root(work: Path) -> None:
	cwd = str(work)
	r = can_use_tool("Bash", {"command": "rm -rf /"}, cwd=cwd)
	assert not r.allowed
	assert r.reason == "destructive_root_delete"


def test_gate_bash_denies_shutdown(work: Path) -> None:
	cwd = str(work)
	r = can_use_tool("Bash", {"command": "shutdown /s /t 0"}, cwd=cwd)
	assert not r.allowed
	assert r.reason == "system_power"


def test_gate_bash_allows_workspace_rm(work: Path) -> None:
	cwd = str(work)
	r = can_use_tool("Bash", {"command": "rm -rf node_modules"}, cwd=cwd)
	# 缺省 bash=default + approval=risk：工作区内写目标自动放行（工作区作用域）。
	assert r.allowed
	assert r.reason == "bash_write_allow"


@pytest.mark.asyncio
async def test_registry_blocks_outside_read(work: Path) -> None:
	reg = ToolRegistry(cwd=str(work))
	reg.register(FileReadTool(cwd=str(work)))
	outside = str(work.parent / "secret_outside.txt")
	Path(outside).write_text("nope", encoding="utf-8")
	abort = AbortController()
	result = await reg.run(
		ToolUse(id="1", name="Read", input={"file_path": outside}),
		abort,
	)
	assert result.is_error
	# 无应答者（coordinator=None）：区外读走 ASK 后立刻按"审批不可用"落 DENY，
	# 文案必须点名是哪一档拦住的，不能回退成旧的 path_outside_working_directory。
	assert "no resolver: read_outside_working_directory" in result.content


@pytest.mark.asyncio
async def test_registry_allows_outside_read_in_max_mode(
	work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	# max 档（never）：允许读取工作区外（如跨目录找日志文件），
	# 且工具内 check_permissions 不二次拦截。
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	reg = ToolRegistry(cwd=str(work))
	reg.register(FileReadTool(cwd=str(work)))
	outside = str(work.parent / "log.txt")
	Path(outside).write_text("logline", encoding="utf-8")
	abort = AbortController()
	result = await reg.run(
		ToolUse(id="1", name="Read", input={"file_path": outside}),
		abort,
	)
	assert not result.is_error
	assert "logline" in result.content


@pytest.mark.asyncio
async def test_registry_allows_inside_read(work: Path) -> None:
	reg = ToolRegistry(cwd=str(work))
	reg.register(FileReadTool(cwd=str(work)))
	abort = AbortController()
	result = await reg.run(
		ToolUse(
			id="1",
			name="Read",
			input={"file_path": str(work / "safe.txt")},
		),
		abort,
	)
	assert not result.is_error
	assert "hello" in result.content


@pytest.mark.asyncio
async def test_registry_echo_unaffected(work: Path) -> None:
	reg = ToolRegistry(cwd=str(work))
	reg.register(EchoTool())
	abort = AbortController()
	result = await reg.run(
		ToolUse(id="1", name="echo", input={"text": "ping"}),
		abort,
	)
	assert not result.is_error


def test_build_default_registry_binds_cwd(work: Path) -> None:
	reg = build_default_registry(cwd=str(work))
	assert Path(reg.cwd) == work.resolve()
	assert reg.get("Read") is not None
	assert reg.get("Bash") is not None


def test_symlink_escape_denied_by_path_jail(work: Path) -> None:
	from permissions.filesystem import (
		PermissionDecision,
		check_write_permission_for_path,
		default_permission_context,
		path_in_allowed_working_path,
	)

	outside = work.parent / "secret_link_target.txt"
	outside.write_text("secret", encoding="utf-8")
	link = work / "escape_link"
	try:
		link.symlink_to(outside)
	except OSError:
		pytest.skip("symlink not permitted on this platform/user")
	assert not path_in_allowed_working_path(str(link), cwd=str(work))
	d = check_write_permission_for_path(
		str(link), context=default_permission_context(str(work))
	)
	assert d == PermissionDecision.DENY


def _make_dir_link(link: Path, target: Path) -> bool:
	"""软链优先（POSIX/开发者模式），失败回退 Windows junction（无需管理员）。"""
	try:
		link.symlink_to(target, target_is_directory=True)
		return True
	except OSError:
		pass
	try:
		proc = subprocess.run(
			["cmd", "/c", "mklink", "/J", str(link), str(target)],
			capture_output=True,
			text=True,
		)
	except OSError:
		return False
	return proc.returncode == 0 and link.is_dir()


def test_symlink_into_secret_dir_hits_secret_gate(work: Path) -> None:
	"""PERM-04（09-10 复核）：软链/junction 指向密钥目录时，组件扫描必须看 realpath。

	同工作区内直接路径 `home/.ssh/config` 是硬 DENY，而 `link/config`
	（link → home/.ssh）字面组件里没有任何密钥名 ⇒ 旧实现直接放行。
	"""
	secret = work / "home" / ".ssh"
	secret.mkdir(parents=True)
	(secret / "config").write_text("Host x\n", encoding="utf-8")
	link = work / "link"
	if not _make_dir_link(link, secret):
		pytest.skip("symlink/junction not permitted on this platform/user")

	from permissions.filesystem import is_secret_path

	# 直接路径：既有硬 DENY（对照，两种形态修前修后都应成立）
	direct = str(secret / "config")
	assert is_secret_path(direct, cwd=str(work))
	d_direct = check_read_permission_for_path(
		direct, context=default_permission_context(str(work))
	)
	assert d_direct == PermissionDecision.DENY
	# 软链路径：必须同判（修前字面扫描放行 = 逃逸）
	linked = str(link / "config")
	assert is_secret_path(linked, cwd=str(work))
	assert is_dangerous_path(linked, cwd=str(work))
	d_linked = check_read_permission_for_path(
		linked, context=default_permission_context(str(work))
	)
	assert d_linked == PermissionDecision.DENY
	# 方向控制：普通文件的字面形态不受影响
	assert not is_secret_path(str(work / "safe.txt"), cwd=str(work))
