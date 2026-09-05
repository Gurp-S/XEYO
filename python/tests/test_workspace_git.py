"""工作区 Git 只读接口：status / log / branches / 文件 diff。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

from server.workspace_git import (  # noqa: E402
	read_file_diff,
	read_git_branches,
	read_git_log,
	read_git_status,
)


def _make_repo(root: Path) -> None:
	root.mkdir()
	subprocess.run(["git", "init", "-q"], cwd=root, check=True)
	subprocess.run(["git", "config", "user.email", "t@example.test"], cwd=root, check=True)
	subprocess.run(["git", "config", "user.name", "tester"], cwd=root, check=True)
	(root / "hello.txt").write_text("v1\n", encoding="utf-8")
	subprocess.run(["git", "add", "hello.txt"], cwd=root, check=True)
	subprocess.run(["git", "commit", "-q", "-m", "init commit"], cwd=root, check=True)


def test_status_reports_count_entries(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	(root / "hello.txt").write_text("v2\n", encoding="utf-8")
	(root / "new.txt").write_text("n\n", encoding="utf-8")
	subprocess.run(["git", "add", "new.txt"], cwd=root, check=True)

	status = read_git_status(str(root))
	assert status["repo"] is True
	assert status["clean"] is False
	assert status["branch"] == "main" or status["branch"] == "master"
	assert status["counts"]["unstaged"] == 1
	assert status["counts"]["staged"] == 1
	assert status["counts"]["untracked"] == 0
	assert status["unstaged"][0]["path"] == "hello.txt"
	assert status["staged"][0]["path"] == "new.txt"


def test_status_clean_repo(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	status = read_git_status(str(root))
	assert status["clean"] is True
	assert status["counts"] == {"staged": 0, "unstaged": 0, "untracked": 0}


def test_log_lists_commits_newest_first(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	log = read_git_log(str(root), limit=10)
	assert log["repo"] is True
	assert len(log["commits"]) >= 1
	first = log["commits"][0]
	assert first["subject"] == "init commit"
	assert first["author"] == "tester"
	assert first["short"] and first["hash"]


def test_branches_marks_current(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	branches = read_git_branches(str(root))
	assert branches["repo"] is True
	assert branches["current"] in ("main", "master")
	assert branches["current"] in branches["branches"]


def test_diff_modified_vs_head(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	(root / "hello.txt").write_text("v2\n", encoding="utf-8")
	result = read_file_diff(str(root), "hello.txt")
	assert result["repo"] is True
	assert result["kind"] == "diff"
	assert "-v1" in result["diff"] and "+v2" in result["diff"]


def test_diff_untracked_synthesized(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	(root / "draft.md").write_text("# draft\n", encoding="utf-8")
	result = read_file_diff(str(root), "draft.md")
	assert result["kind"] == "untracked"
	assert "new file mode" in result["diff"]
	assert "+# draft" in result["diff"]


def test_diff_unchanged(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	result = read_file_diff(str(root), "hello.txt")
	assert result["kind"] == "unchanged"
	assert result["diff"] in (None, "")


def test_non_repo_returns_repo_false(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	assert read_git_status(str(root))["repo"] is False
	assert read_git_log(str(root), 5)["commits"] == []
	assert read_git_branches(str(root))["current"] is None


def test_diff_blocks_outside_workspace(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	_make_repo(root)
	with pytest.raises(PermissionError):
		read_file_diff(str(root), "../outside.txt")
