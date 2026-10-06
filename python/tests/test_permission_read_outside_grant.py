"""第二刀：区外读从静默 DENY 改成 ASK，一次确认换「该目录及其子目录」的授权。

四条红线，缺一行都算没做：
1. 写侧的区外边界不放宽（仍 DENY）；
2. 密钥硬 DENY 必须先于区外判定，且 DENY 归因同序（否则区外密钥会被标成"问一句就能读"）；
3. 授权粒度是目录前缀——既不能过放（放行一个=放行所有区外读），也不能欠放
   （同目录第二个文件又问一遍）；
4. 工体内那道二次门必须认 registry 的批准位，否则用户点完"允许"仍被静默 DENY。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

import pytest

from engine.workspace_context import WorkspaceContext, set_workspace_context
from permissions.filesystem import mark_permission_preapproved
from permissions.policy import evaluate_policy, permission_mode, set_permission_mode
from permissions.store import (
	READ_OUTSIDE_RULE,
	_READ_GRANT_TOOLS,
	PermissionGrantStore,
	grant_fingerprint,
	grantable_read_dir,
	read_dir_fingerprint,
	read_grant_path,
)


class Env(NamedTuple):
	ws: Path
	home: Path
	outside: Path


@pytest.fixture
def env(tmp_path, monkeypatch):
	"""独立家目录 + 独立工作区 + 独立区外目录 + 不共享的 grant store。

	家目录必须是夹具：反向校要问"家目录那一格能不能被记住"，而真实 `~/.xeyo`
	是指纹之外唯一能走通的后代分支，留着两条分支都判不到。
	"""
	home = tmp_path / "home"
	ws = tmp_path / "ws"
	outside = tmp_path / "outside"
	(home / ".ssh").mkdir(parents=True)
	(ws / ".git").mkdir(parents=True)
	outside.mkdir(parents=True)
	monkeypatch.setenv("HOME", str(home))
	monkeypatch.setenv("USERPROFILE", str(home))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "memdir"))
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "default")
	monkeypatch.delenv("XEYO_GRANT_TTL_SEC", raising=False)
	import permissions.store as st

	monkeypatch.setattr(st, "_default_grant_store", PermissionGrantStore(persist=False))
	set_permission_mode(None)
	set_workspace_context(WorkspaceContext(session_id="s1", cwd=str(ws)))
	yield Env(ws=ws, home=home, outside=outside)
	set_workspace_context(None)
	set_permission_mode(None)


def _store(monkeypatch) -> PermissionGrantStore:
	store = PermissionGrantStore(persist=False)
	monkeypatch.setattr("permissions.store.default_grant_store", lambda: store)
	return store


def _grant(store, tool: str, path, ws: Path, *, key: str = "file_path") -> str:
	"""按生产同源链路落一条授权：grant_fingerprint(tool_input, matched_rule) → add。"""
	fp = grant_fingerprint(tool, {key: str(path)}, matched_rule=READ_OUTSIDE_RULE)
	grant = store.add(tool_name=tool, fingerprint=fp, scope=str(ws), actor="test")
	return grant.grant_id if grant else ""


def test_outside_read_asks_instead_of_silent_deny(env) -> None:
	target = env.outside / "a.txt"
	r = evaluate_policy("Read", {"file_path": str(target)}, cwd=str(env.ws))
	assert r.decision == "ask"
	assert r.matched_rule == READ_OUTSIDE_RULE
	assert r.reason == "read_outside_working_directory"
	assert "outside the workspace" in (r.prompt or "")


def test_outside_write_still_denies(env) -> None:
	target = env.outside / "a.txt"
	r = evaluate_policy(
		"Write", {"file_path": str(target), "content": "x"}, cwd=str(env.ws)
	)
	assert r.decision == "deny"
	assert r.reason == "path_outside_working_directory"


def test_outside_secret_denies_before_outside_ask(env) -> None:
	"""顺序校：区外的密钥路径是 DENY，且归因说 secret——不能降成可确认的 ASK，
	也不能被标成"区外"（那会让人以为问一句就能读私钥）。"""
	key = env.home / ".ssh" / "id_rsa"
	key.write_text("k", encoding="utf-8")
	r = evaluate_policy("Read", {"file_path": str(key)}, cwd=str(env.ws))
	assert r.decision == "deny"
	assert r.reason == "secret_path"


def test_grant_covers_directory_subtree(env, monkeypatch) -> None:
	store = _store(monkeypatch)
	first = env.outside / "a.txt"
	assert evaluate_policy("Read", {"file_path": str(first)}, cwd=str(env.ws)).decision == "ask"
	assert _grant(store, "Read", first, env.ws)
	# 同目录第二个文件：不再问。
	second = env.outside / "b.txt"
	r = evaluate_policy("Read", {"file_path": str(second)}, cwd=str(env.ws))
	assert r.decision == "allow"
	assert r.matched_rule == "grant_store"
	# 子目录在同一扇门内。
	child_dir = env.outside / "sub"
	child_dir.mkdir()
	assert (
		evaluate_policy(
			"Read", {"file_path": str(child_dir / "c.txt")}, cwd=str(env.ws)
		).decision
		== "allow"
	)


def test_grant_does_not_open_sibling_directory(env, monkeypatch) -> None:
	"""防过放：授权 notes/ 不得连带放开 other/。"""
	store = _store(monkeypatch)
	_grant(store, "Read", env.outside / "a.txt", env.ws)
	sibling = env.ws.parent / "other"
	sibling.mkdir()
	r = evaluate_policy("Read", {"file_path": str(sibling / "x.txt")}, cwd=str(env.ws))
	assert r.decision == "ask"


def test_read_grant_never_reaches_write_side(env, monkeypatch) -> None:
	store = _store(monkeypatch)
	_grant(store, "Read", env.outside / "a.txt", env.ws)
	w = evaluate_policy(
		"Write", {"file_path": str(env.outside / "a.txt"), "content": "x"}, cwd=str(env.ws)
	)
	assert w.decision == "deny"


def test_glob_grant_uses_path_key(env, monkeypatch) -> None:
	"""Glob/Grep 的入参键是 path，不是 file_path——指纹取不到路径就记不住。"""
	store = _store(monkeypatch)
	gid = _grant(store, "Glob", env.outside, env.ws, key="path")
	assert gid
	r = evaluate_policy(
		"Glob", {"pattern": "*.txt", "path": str(env.outside)}, cwd=str(env.ws)
	)
	assert r.decision == "allow"


def test_root_home_and_ancestors_are_not_grantable(env) -> None:
	"""一次确认不许把整机或整个用户剖面开成门。"""
	assert read_dir_fingerprint(str(env.home / "top.txt")) == ""
	assert grantable_read_dir(str(env.home)) == ""
	assert read_dir_fingerprint(str(env.ws.parent / "x.txt")) == ""  # 家的祖先
	assert read_dir_fingerprint(str(env.outside / "a.txt")) != ""
	drive_root = os.path.abspath(os.sep)
	assert read_dir_fingerprint(os.path.join(drive_root, "x.txt")) == ""
	store = PermissionGrantStore(persist=False)
	assert store.add(tool_name="Read", fingerprint="", scope=str(env.ws)) is None


def test_fingerprint_namespaces_do_not_collide(env) -> None:
	fp_read = grant_fingerprint(
		"Read", {"file_path": str(env.outside / "y.txt")}, matched_rule=READ_OUTSIDE_RULE
	)
	fp_write_tool_with_rule = grant_fingerprint(
		"Edit", {"file_path": str(env.outside / "y.txt")}, matched_rule=READ_OUTSIDE_RULE
	)
	fp_plain = grant_fingerprint("Write", None, matched_rule="write_confirm_ask")
	assert fp_read.startswith("read-dir:v1:")
	# 非只读工具带区外规则名属意外：落空串，不许记住。
	assert fp_write_tool_with_rule == ""
	assert fp_plain == "write_confirm_ask"
	assert read_grant_path({"notebook_path": str(env.outside / "nb.ipynb")}) == str(
		env.outside / "nb.ipynb"
	)


def test_mode_always_still_asks_every_time(env, monkeypatch) -> None:
	"""permission_mode=always（用户显式逐条确认）不得被授权穿越。"""
	store = _store(monkeypatch)
	_grant(store, "Read", env.outside / "a.txt", env.ws)
	set_permission_mode("always")
	try:
		assert permission_mode() == "always"
		r = evaluate_policy("Read", {"file_path": str(env.outside / "a.txt")}, cwd=str(env.ws))
		assert r.decision == "ask"
	finally:
		set_permission_mode(None)


def test_ungrantable_outside_dir_stays_hard_deny(env) -> None:
	"""记不住的格子不开面板：区外但落在家目录本身那一层 → 仍 DENY，
	且归因诚实（承诺"不再询问"的面板绝不能出现在记住不了的路径上）。"""
	target = env.home / "top.txt"
	r = evaluate_policy("Read", {"file_path": str(target)}, cwd=str(env.ws))
	assert r.decision == "deny"
	assert r.reason == "path_outside_working_directory"
	assert r.matched_rule == "read_deny"


def test_read_tool_lists_do_not_diverge() -> None:
	"""`tools.meta.READ_PATH_TOOLS` 与 store 的授权白名单不许分叉。

	store 不 import tools/（方向依赖），所以两份名单是手抄的——漏一个的后果不是
	报错，而是那个工具的区外读永远问、永远记不住（静默欠放）。
	"""
	from tools.meta import READ_PATH_TOOLS

	missing = {n.strip().lower() for n in READ_PATH_TOOLS} - _READ_GRANT_TOOLS
	assert not missing, f"这些只读工具无法被记住：{sorted(missing)}"


def test_tool_body_honours_registry_approval_for_outside_read(env) -> None:
	"""红线 4：工具层的根集合比策略层窄（本层不读 .xeyo-policy.json），
	区外读在工体内一定是 ASK——不认 registry 批准位就会把已放行的读重新静默 DENY。"""
	from tools.file_read_tool.file_read_tool import FileReadTool

	target = env.outside / "a.txt"
	target.write_text("hello", encoding="utf-8")
	tool = FileReadTool(cwd=str(env.ws))
	inp = {"file_path": str(target)}
	# 未批准：工体内拦住。
	assert tool.check_permissions(inp) is False
	# registry 已裁决（含用户确认后 skip_ask）：必须放行。
	with mark_permission_preapproved(True):
		assert tool.check_permissions(inp) is True
