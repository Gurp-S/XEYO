from __future__ import annotations

from engine.shadow_git import ShadowGit
from engine.workspace_revision import WorkspaceRevision


def test_revision_changes_when_modified_file_content_changes(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "tracked.txt"
    target.write_text("base", encoding="utf-8")

    shadow = ShadowGit(workspace)
    shadow.snapshot("base")
    revision = WorkspaceRevision(workspace)

    target.write_text("first change", encoding="utf-8")
    first = revision.calculate(paths=["tracked.txt"])
    target.write_text("second change", encoding="utf-8")
    second = revision.calculate(paths=["tracked.txt"])

    assert first != second


def test_scoped_revision_ignores_unrelated_untracked(tmp_path) -> None:
    """Vite/test noise outside fingerprint_paths must not change the revision."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "agent.txt"
    target.write_text("base", encoding="utf-8")

    shadow = ShadowGit(workspace)
    shadow.snapshot("base")
    revision = WorkspaceRevision(workspace)

    target.write_text("agent edit", encoding="utf-8")
    before = revision.calculate(paths=["agent.txt"])
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "noise.js").write_text("x", encoding="utf-8")
    (workspace / ".vite").mkdir()
    (workspace / ".vite" / "deps").write_text("y", encoding="utf-8")
    after = revision.calculate(paths=["agent.txt"])

    assert before == after


def test_empty_paths_is_head_only(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shadow = ShadowGit(workspace)
    shadow.snapshot("empty")
    revision = WorkspaceRevision(workspace)

    first = revision.calculate(paths=[])
    (workspace / "noise.bin").write_bytes(b"one")
    second = revision.calculate(paths=[])

    assert first == second


def test_legacy_full_revision_still_sees_untracked(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shadow = ShadowGit(workspace)
    shadow.snapshot("empty")
    revision = WorkspaceRevision(workspace)

    target = workspace / "new.bin"
    target.write_bytes(b"one")
    first = revision.calculate()
    target.write_bytes(b"two")
    second = revision.calculate()

    assert first != second
