"""P3 git 基线 diff 佐证：截断上限 / 路径命中判定 / 工件读写 / git 收集。"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from memory.memdir import workspace_id
from memory.workspace_diff import (
	MAX_BYTES,
	_bounded_text,
	candidate_path_tokens,
	collect,
	git_head,
	load_artifact_paths,
	matches,
	remove_artifact,
	write_artifact,
)


def test_bound_truncates_with_marker():
	big = "x" * (MAX_BYTES + 1000)
	text, truncated = _bounded_text(big, max_bytes=MAX_BYTES)
	assert truncated is True
	assert text.endswith("[workspace diff truncated at %d bytes]" % MAX_BYTES + "\n")
	small = "ok text"
	out, t = _bounded_text(small)
	assert t is False
	assert out == small


def test_matches_path_heuristics():
	assert matches({"src/a.py"}, {"src/a.py"}) is True
	assert matches({"src/a.py"}, {"deep/src/a.py"}) is True
	assert matches({"a.py"}, {"src/a.py"}) is True  # 裸文件名是 diff 路径的后缀 → 命中
	assert matches({"a.py"}, {"other/b.py"}) is False
	assert matches({"src/a.py"}, {"other/b.py"}) is False
	assert matches(set(), {"src/a.py"}) is False
	assert matches({"src/a.py"}, set()) is False


def test_candidate_path_tokens():
	toks = candidate_path_tokens("改用 src/run.py 的逻辑", ["path:src/run.py", "main_harvest"])
	assert "src/run.py" in toks


def _git_available() -> bool:
	return shutil.which("git") is not None


def _git(repo, *args):
	return subprocess.run(
		["git", "-C", str(repo), *args],
		capture_output=True,
		text=True,
		encoding="utf-8",
		check=True,
	)


def test_git_collect_workspace_diff(tmp_path):
	if not _git_available():
		pytest.skip("git not available")
	repo = tmp_path / "repo"
	repo.mkdir()
	_git(repo, "init")
	_git(repo, "config", "user.email", "t@t")
	_git(repo, "config", "user.name", "t")
	(repo / "a.py").write_text("v1\n", encoding="utf-8")
	_git(repo, "add", ".")
	_git(repo, "commit", "-m", "init")
	head0 = git_head(str(repo))
	assert head0
	# 未提交改动 + 新文件
	(repo / "a.py").write_text("v2\n", encoding="utf-8")
	(repo / "b.py").write_text("x\n", encoding="utf-8")
	diff = collect(str(repo), baseline_sha="")
	assert diff is not None
	assert "a.py" in diff.paths and "b.py" in diff.paths
	assert diff.head_sha == head0
	assert diff.text
	# 提交后再以 head0 为基线 → 提交内 diff 也可见
	_git(repo, "add", ".")
	_git(repo, "commit", "-m", "change")
	diff2 = collect(str(repo), baseline_sha=head0)
	assert diff2 is not None
	assert "a.py" in diff2.paths and "b.py" in diff2.paths


def test_collect_no_git_returns_none(tmp_path):
	plain = tmp_path / "plain"
	plain.mkdir()
	assert collect(str(plain)) is None


def test_artifact_roundtrip(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	repo = tmp_path / "repo"
	repo.mkdir()
	wsid = workspace_id(str(repo))
	from memory.workspace_diff import WorkspaceDiff

	d = WorkspaceDiff(
		paths=["src/a.py", "spill.txt"],
		text="# diff\n- M src/a.py\n+ spill.txt\n",
		baseline_sha="b0",
		head_sha="h1",
	)
	path = write_artifact(wsid, d)
	assert path is not None
	paths = load_artifact_paths(wsid)
	assert "src/a.py" in paths
	remove_artifact(wsid)
	assert not path.exists()
	assert load_artifact_paths(wsid) == set()


def test_state_roundtrip_baseline_sha(tmp_path, monkeypatch):
	"""nightshift 状态基线字段往返（P3 基线不丢）。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	from memory.nightshift import NightShiftState, load_state, save_state

	st = NightShiftState(baseline_sha="abc123")
	save_state(wsid, st)
	assert load_state(wsid).baseline_sha == "abc123"
