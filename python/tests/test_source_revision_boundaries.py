"""源码版本查询的目录归属与失败降级回归。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from common import source_revision
from common.revision_probe import git_revision


def _git(root: Path, *args: str) -> str:
	return subprocess.check_output(
		["git", "-C", str(root), *args], text=True, encoding="utf-8"
	).strip()


@pytest.fixture
def source_tree(tmp_path):
	root = tmp_path / "project"
	source = root / "python"
	source.mkdir(parents=True)
	_git(root, "init", "-q")
	_git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
		"commit", "--allow-empty", "-qm", "test fixture")
	return source, _git(root, "rev-parse", "--short", "HEAD")


def test_snapshot_uses_source_repository(source_tree):
	source, expected = source_tree
	assert source_revision.snapshot(source)["repo_rev"] == expected


def test_probe_finds_repository_from_nested_source(source_tree):
	source, expected = source_tree
	nested = source / "package" / "nested"
	nested.mkdir(parents=True)
	assert git_revision(nested) == expected


def test_probe_without_repository(tmp_path):
	assert git_revision(tmp_path) == ""


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("git", 5)])
def test_probe_unavailable_git_returns_empty(monkeypatch, tmp_path, error):
	def unavailable(*args, **kwargs):
		raise error
	monkeypatch.setattr(subprocess, "run", unavailable)
	assert git_revision(tmp_path) == ""
