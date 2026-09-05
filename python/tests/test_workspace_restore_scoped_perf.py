"""Probe: scoped restore must not invoke full-tree `git add -A`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from engine.shadow_git import ShadowGit
from engine.workspace_restore import WorkspaceRestoreTransaction
from engine.workspace_revision import WorkspaceRevision


def test_scoped_restore_uses_paths_snapshot_not_add_all(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    f = workspace / "a.txt"
    f.write_text("v1", encoding="utf-8")
    shadow = ShadowGit(workspace)
    base = shadow.snapshot("base")
    f.write_text("v2", encoding="utf-8")
    rev = WorkspaceRevision(workspace).calculate(paths=["a.txt"])

    calls: list[tuple] = []
    real_snapshot = ShadowGit.snapshot

    def wrapped(self: ShadowGit, message: str = "Snapshot", *, paths=None):
        calls.append((message, paths))
        return real_snapshot(self, message, paths=paths)

    with patch.object(ShadowGit, "snapshot", wrapped):
        tx = WorkspaceRestoreTransaction(workspace, owner="probe")
        tx.execute(
            base,
            rev,
            path_scope=["a.txt"],
            fingerprint_paths=["a.txt"],
        )

    assert calls, "expected safety/post snapshots"
    for _msg, paths in calls:
        assert paths is not None, "scoped restore must pass paths= (never full add -A)"
        assert "a.txt" in paths
    assert f.read_text(encoding="utf-8") == "v1"
