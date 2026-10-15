"""子代理 worktree 隔离契约测试：隔离 → 回收（干净应用 / 三方合并 / 真冲突回滚）。

只用真 git 仓库与 ``WorktreeIsolation``，不驱动模型：验的是隔离与回收这两件事。
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.agent_tool.worktree_isolation import (
    IsolationUnavailable,
    WorktreeIsolation,
    is_git_repo,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    for name, body in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_non_git_path_is_unavailable(tmp_path):
    assert is_git_repo(tmp_path) is False
    iso = WorktreeIsolation(tmp_path, "t0")
    try:
        with iso:
            raise AssertionError("should not enter")
    except IsolationUnavailable:
        pass


def test_isolated_write_is_merged_back(tmp_path):
    repo = _make_repo(tmp_path, {"a.txt": "one\n"})
    with WorktreeIsolation(repo, "t1") as iso:
        # 隔离期间主仓看不到这个文件（独立工作树）
        (iso.path / "b.txt").write_text("new\n", encoding="utf-8")
        assert not (repo / "b.txt").exists()
    outcome = iso.outcome
    assert outcome.ok and outcome.merged and not outcome.no_changes
    assert outcome.changed_files == ["b.txt"]
    # 回收后落在主工作树（交互式语义：不推 ref，只改文件）
    assert (repo / "b.txt").read_text(encoding="utf-8") == "new\n"
    # 完成即弃
    assert not Path(outcome.worktree).exists()


def test_no_changes_is_reported(tmp_path):
    repo = _make_repo(tmp_path, {"a.txt": "one\n"})
    with WorktreeIsolation(repo, "t2") as iso:
        pass
    assert iso.outcome.ok and iso.outcome.no_changes
    assert not Path(iso.outcome.worktree).exists()


def test_disjoint_regions_of_same_file_merge(tmp_path):
    """同一文件、相隔很远的两处改动应自动合上（不需要人工介入）。"""
    lines = [f"line{i}\n" for i in range(1, 21)]
    repo = _make_repo(tmp_path, {"f.txt": "".join(lines)})
    # 主工作树改第 2 行（未提交）
    edited = list(lines)
    edited[1] = "main-side\n"
    (repo / "f.txt").write_text("".join(edited), encoding="utf-8")

    with WorktreeIsolation(repo, "t3") as iso:
        child = list(lines)
        child[18] = "child-side\n"
        (iso.path / "f.txt").write_text("".join(child), encoding="utf-8")

    outcome = iso.outcome
    assert outcome.merged, outcome.detail
    merged = (repo / "f.txt").read_text(encoding="utf-8")
    assert "main-side" in merged and "child-side" in merged
    assert not Path(outcome.worktree).exists()


def test_true_conflict_keeps_worktree_and_rolls_back(tmp_path):
    """同一行的真冲突：不写冲突标记，主仓逐字回滚，隔离副本保留。"""
    repo = _make_repo(tmp_path, {"c.txt": "l1\nl2\nl3\n"})
    (repo / "c.txt").write_text("l1\nMAIN\nl3\n", encoding="utf-8")
    before = (repo / "c.txt").read_bytes()

    with WorktreeIsolation(repo, "t4") as iso:
        (iso.path / "c.txt").write_text("l1\nCHILD\nl3\n", encoding="utf-8")

    outcome = iso.outcome
    assert outcome.ok and not outcome.merged
    assert outcome.conflicts == ["c.txt"]
    # 主仓逐字回滚到尝试前（用户自己的未提交改动完好）
    assert (repo / "c.txt").read_bytes() == before
    assert b"<<<<<<<" not in (repo / "c.txt").read_bytes()
    # 隔离副本保留，可从 worktree 取回
    assert Path(outcome.worktree).exists()
    assert (Path(outcome.worktree) / "c.txt").read_text(encoding="utf-8") == "l1\nCHILD\nl3\n"


def test_subagent_failure_keeps_worktree_without_merging(tmp_path):
    repo = _make_repo(tmp_path, {"a.txt": "one\n"})
    iso = WorktreeIsolation(repo, "t5")
    try:
        with iso:
            (iso.path / "a.txt").write_text("half-done\n", encoding="utf-8")
            raise RuntimeError("child blew up")
    except RuntimeError:
        pass
    assert iso.outcome.ok is False
    assert iso.outcome.merged is False
    assert "subagent failed" in iso.outcome.detail
    # 主仓未被改动，隔离副本保留
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert Path(iso.outcome.worktree).exists()


def test_summary_is_neutral_facts(tmp_path):
    repo = _make_repo(tmp_path, {"a.txt": "one\n"})
    with WorktreeIsolation(repo, "t6") as iso:
        (iso.path / "a.txt").write_text("two\n", encoding="utf-8")
    text = iso.outcome.summary()
    assert "worktree isolation:" in text
    assert "should" not in text.lower() and "建议" not in text
