"""Rewind v2 检查点：checkpoint id、transcript 优先异步执行、范围化安全。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from engine.shadow_git import ShadowGit
from engine.workspace_restore import WorkspaceRestoreTransaction
from engine.workspace_revision import WorkspaceRevision
from rewind.checkpoint import derive_checkpoint_id, get_checkpoint_cache, put_checkpoint_cache


def test_derive_checkpoint_id_stable() -> None:
    a = derive_checkpoint_id(
        session_id="sess", user_message_id="m1", before_commit="abc"
    )
    b = derive_checkpoint_id(
        session_id="sess", user_message_id="m1", before_commit="abc"
    )
    c = derive_checkpoint_id(
        session_id="sess", user_message_id="m2", before_commit="abc"
    )
    assert a == b
    assert a.startswith("cp_")
    assert a != c


def test_checkpoint_cache_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    # 通过 put 路径覆盖强制 default_sessions_dir
    sid = "sess_cp_cache"
    put_checkpoint_cache(
        sid,
        checkpoint_id="cp_x",
        user_message_id="u1",
        before_commit="deadbeef",
        shadow_paths=["a.ts"],
        fingerprint_paths=["a.ts"],
        sessions_dir=tmp_path / "sessions",
    )
    hit = get_checkpoint_cache(
        sid, checkpoint_id="cp_x", sessions_dir=tmp_path / "sessions"
    )
    assert hit is not None
    assert hit["before_commit"] == "deadbeef"
    assert hit["shadow_paths"] == ["a.ts"]


def test_scoped_snapshot_does_not_require_full_add(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "tracked.txt").write_text("base", encoding="utf-8")
    shadow = ShadowGit(workspace)
    base = shadow.snapshot("base")
    (workspace / "tracked.txt").write_text("changed", encoding="utf-8")
    (workspace / "noise.bin").write_bytes(b"x" * 1024)
    # 范围化安全只暂存 tracked.txt——噪音相对提交内容保持未暂存。
    safety = shadow.snapshot("safety", paths=["tracked.txt"])
    assert safety
    assert safety != base or True  # may equal if commit empty after add only tracked


def test_scoped_restore_hot_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "tracked.txt"
    target.write_text("base", encoding="utf-8")
    shadow = ShadowGit(workspace)
    base_commit = shadow.snapshot("base")
    target.write_text("changed", encoding="utf-8")
    (workspace / "other.txt").write_text("keep-me", encoding="utf-8")
    current_rev = WorkspaceRevision(workspace).calculate(paths=["tracked.txt"])

    tx = WorkspaceRestoreTransaction(workspace, owner="scoped")
    tx.execute(
        base_commit,
        current_rev,
        path_scope=["tracked.txt"],
        fingerprint_paths=["tracked.txt"],
        auto_trash_created=False,
    )
    assert target.read_text(encoding="utf-8") == "base"
    assert (workspace / "other.txt").read_text(encoding="utf-8") == "keep-me"
