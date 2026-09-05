from __future__ import annotations

import pytest

from engine.shadow_git import ShadowGit
from engine.workspace_restore import RestoreError, WorkspaceRestoreTransaction
from engine.workspace_revision import WorkspaceRevision


def test_restore_transaction_reverts_tracked_and_moves_untracked_to_trash(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "tracked.txt"
    target.write_text("base", encoding="utf-8")

    shadow = ShadowGit(workspace)
    base_commit = shadow.snapshot("base")

    target.write_text("changed", encoding="utf-8")
    untracked = workspace / "new.bin"
    untracked.write_bytes(b"data")
    
    current_rev = WorkspaceRevision(workspace).calculate()

    tx = WorkspaceRestoreTransaction(workspace, owner="test")
    new_rev = tx.execute(
        base_commit,
        current_rev,
        trash_candidates=["new.bin"]
    )

    assert target.read_text(encoding="utf-8") == "base"
    assert not untracked.exists()
    
    # Verify trash was populated
    trash_root = workspace / ".xy-trash"
    trash_dirs = list(trash_root.iterdir())
    assert len(trash_dirs) == 1
    assert (trash_dirs[0] / "new.bin").read_bytes() == b"data"
    
    assert new_rev != current_rev
    assert WorkspaceRevision(workspace).calculate() == new_rev


def test_restore_transaction_rolls_back_to_safety_on_fault(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "tracked.txt"
    target.write_text("base", encoding="utf-8")

    shadow = ShadowGit(workspace)
    base_commit = shadow.snapshot("base")

    target.write_text("changed", encoding="utf-8")
    untracked = workspace / "new.bin"
    untracked.write_bytes(b"data")
    
    current_rev = WorkspaceRevision(workspace).calculate()

    def fault(phase: str) -> None:
        if phase == "TREE_RESTORING":
            raise RuntimeError("Injected fault during tree restore")

    tx = WorkspaceRestoreTransaction(workspace, owner="test")
    with pytest.raises(RestoreError, match="Injected fault"):
        tx.execute(
            base_commit,
            current_rev,
            trash_candidates=["new.bin"],
            fault_inject=fault
        )

    # Workspace should be fully restored to the pre-transaction state
    assert target.read_text(encoding="utf-8") == "changed"
    assert untracked.read_bytes() == b"data"
    
    # Trash directory for this transaction should be empty/reverted
    trash_root = workspace / ".xy-trash"
    if trash_root.exists():
        for tx_dir in trash_root.iterdir():
            assert not list(tx_dir.rglob("*.*"))


def test_auto_trash_created_removes_files_absent_from_target(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "tracked.txt"
    target.write_text("base", encoding="utf-8")

    shadow = ShadowGit(workspace)
    base_commit = shadow.snapshot("base")

    target.write_text("changed", encoding="utf-8")
    created = workspace / "icon.svg"
    created.write_text("<svg/>", encoding="utf-8")
    current_rev = WorkspaceRevision(workspace).calculate()

    tx = WorkspaceRestoreTransaction(workspace, owner="auto-trash")
    tx.execute(base_commit, current_rev, auto_trash_created=True)

    assert target.read_text(encoding="utf-8") == "base"
    assert not created.exists()
    trash_root = workspace / ".xy-trash"
    assert any((p / "icon.svg").is_file() for p in trash_root.iterdir())


def test_restore_recovers_non_ascii_filename_content(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    docs = workspace / "docs"
    docs.mkdir(parents=True)
    target = docs / "起步阶段评测结果.md"
    target.write_text("完整评测内容\n第二行", encoding="utf-8")

    shadow = ShadowGit(workspace)
    base_commit = shadow.snapshot("with chinese file")

    target.write_text("", encoding="utf-8")
    current_rev = WorkspaceRevision(workspace).calculate()

    tx = WorkspaceRestoreTransaction(workspace, owner="chinese-path")
    tx.execute(base_commit, current_rev)

    assert target.read_text(encoding="utf-8") == "完整评测内容\n第二行"


def test_unescape_git_octal_path() -> None:
    quoted = r'docs/\350\265\267\346\255\245\351\230\266\346\256\265\350\257\204\346\265\213\347\273\223\346\236\234.md'
    assert (
        WorkspaceRestoreTransaction._unescape_git_path(quoted)
        == "docs/起步阶段评测结果.md"
    )
