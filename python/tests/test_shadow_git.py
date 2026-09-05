from __future__ import annotations

from engine.shadow_git import ShadowGit, _git_text_encodings, decode_git_bytes
from engine.workspace_restore import WorkspaceRestoreTransaction


def test_snapshot_captures_workspace_and_reuses_unchanged_head(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_text("before", encoding="utf-8")

    shadow = ShadowGit(workspace)
    first = shadow.snapshot("before")
    assert first
    assert shadow.head_commit() == first

    unchanged = shadow.snapshot("unchanged")
    assert unchanged == first

    target.write_text("after", encoding="utf-8")
    changed = shadow.snapshot("after")
    assert changed
    assert changed != first


def test_shadow_git_excludes_its_own_lock_directory(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shadow = ShadowGit(workspace)
    shadow.init_if_needed()
    (workspace / ".xy-shadow-git" / "workspace.lock").write_text("lock", encoding="utf-8")

    shadow.snapshot("empty workspace")
    status = shadow._run(["status", "--porcelain"]).stdout
    assert ".xy-shadow-git" not in status


def test_shadow_git_run_decodes_non_ascii_paths(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    chinese = workspace / "docs"
    chinese.mkdir()
    target = chinese / "起步阶段评测结果.md"
    target.write_text("评测内容", encoding="utf-8")

    shadow = ShadowGit(workspace)
    commit = shadow.snapshot("chinese path")
    listed = shadow._run(["ls-tree", "-r", "-z", commit]).stdout
    assert "起步阶段评测结果.md" in listed
    assert "评测内容" not in listed  # tree lists paths, not blob body


def test_decode_git_bytes_accepts_utf8_and_gbk() -> None:
    assert "utf-8" in [e.lower() for e in _git_text_encodings()]
    assert decode_git_bytes("起步".encode("utf-8")) == "起步"
    assert decode_git_bytes("起步".encode("gbk")) == "起步"


def test_decode_tree_path_prefers_on_disk_encoding(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    docs = workspace / "docs"
    docs.mkdir(parents=True)
    target = docs / "起步阶段评测结果.md"
    target.write_text("x", encoding="utf-8")

    tx = WorkspaceRestoreTransaction(workspace, owner="enc")
    utf8_path = "docs/起步阶段评测结果.md".encode("utf-8")
    gbk_path = "docs/起步阶段评测结果.md".encode("gbk")
    assert tx._decode_tree_path(utf8_path) == "docs/起步阶段评测结果.md"
    assert tx._decode_tree_path(gbk_path) == "docs/起步阶段评测结果.md"
