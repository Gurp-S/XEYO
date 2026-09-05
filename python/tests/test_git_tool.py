"""Git read-only agent tool."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engine.abort import AbortController
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.git_tool import GitTool
from tools.git_tool.prompt import WRITE_REJECT


def _init_repo(root: Path) -> None:
	if shutil.which("git") is None:
		pytest.skip("git not installed")
	subprocess.run(["git", "init", "-q"], cwd=root, check=True)
	subprocess.run(
		["git", "config", "user.email", "t@t.test"], cwd=root, check=True
	)
	subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
	(root / "a.txt").write_text("hi\n", encoding="utf-8")
	subprocess.run(["git", "add", "."], cwd=root, check=True)
	subprocess.run(
		["git", "commit", "-q", "-m", "first"], cwd=root, check=True
	)


@pytest.mark.asyncio
async def test_git_summary(tmp_path: Path) -> None:
	_init_repo(tmp_path)
	tool = GitTool(cwd=str(tmp_path))
	r = await tool.execute({"action": "summary"}, AbortController())
	assert not r.is_error
	assert "branch:" in r.content
	assert "dirty:" in r.content
	assert "first" in r.content


@pytest.mark.asyncio
async def test_git_status_and_log(tmp_path: Path) -> None:
	_init_repo(tmp_path)
	tool = GitTool(cwd=str(tmp_path))
	st = await tool.execute({"action": "status"}, AbortController())
	assert not st.is_error
	assert "Not a git repository" not in st.content
	assert "branch:" in st.content

	log = await tool.execute({"action": "log", "limit": 5}, AbortController())
	assert not log.is_error
	assert "first" in log.content


@pytest.mark.asyncio
async def test_git_not_a_repo(tmp_path: Path) -> None:
	tool = GitTool(cwd=str(tmp_path))
	r = await tool.execute({"action": "status"}, AbortController())
	assert not r.is_error
	assert "Not a git repository" in r.content


@pytest.mark.asyncio
async def test_git_rejects_commit(tmp_path: Path) -> None:
	tool = GitTool(cwd=str(tmp_path))
	r = await tool.execute({"action": "commit"}, AbortController())
	assert r.is_error
	assert "read-only" in r.content.lower() or WRITE_REJECT[:20] in r.content


@pytest.mark.asyncio
async def test_git_diff_requires_path(tmp_path: Path) -> None:
	_init_repo(tmp_path)
	tool = GitTool(cwd=str(tmp_path))
	r = await tool.execute({"action": "diff"}, AbortController())
	assert r.is_error
	assert "path" in r.content.lower()


def test_git_policy_always_allow(tmp_path: Path) -> None:
	d = evaluate_policy("Git", {"action": "status"}, cwd=str(tmp_path))
	assert d.decision == PermissionDecision.ALLOW


def test_parse_unified_new_range() -> None:
	from server.workspace_git import _parse_unified_new_range

	assert _parse_unified_new_range("@@ -10,2 +20,3 @@") == (20, 22)
	assert _parse_unified_new_range("@@ -1 +1 @@") == (1, 1)
	assert _parse_unified_new_range("@@ -5,2 +0,0 @@") is None


@pytest.mark.asyncio
async def test_git_summary_touched_symbols(tmp_path: Path) -> None:
	_init_repo(tmp_path)
	mod = tmp_path / "mod.py"
	mod.write_text(
		"def keep():\n\treturn 1\n\n\ndef target():\n\treturn 2\n\n\ndef other():\n\treturn 3\n",
		encoding="utf-8",
	)
	subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)
	subprocess.run(["git", "commit", "-q", "-m", "add mod"], cwd=tmp_path, check=True)
	mod.write_text(
		"def keep():\n\treturn 1\n\n\ndef target():\n\treturn 99\n\n\ndef other():\n\treturn 3\n",
		encoding="utf-8",
	)
	tool = GitTool(cwd=str(tmp_path))
	r = await tool.execute({"action": "summary"}, AbortController())
	assert not r.is_error
	assert "touched:" in r.content
	assert "target" in r.content
