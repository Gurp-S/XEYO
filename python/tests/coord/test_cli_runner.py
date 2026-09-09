"""coord CLI runner 冒烟：flag 门 + 循环编排（注入 scripted work_fn，离线不联网）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coord.file_store import CoordFileStore
from coord.planner import Planner
from coord.store import STATUS_MERGED, new_task
from coord.worktree import git


def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    for args in (["init", "-b", "main"], ["config", "user.name", "t"],
                 ["config", "user.email", "t@t"], ["config", "core.autocrlf", "false"]):
        git(repo, *args)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "seed")
    # flag 开（workspace settings）
    (repo / ".xeyo").mkdir(parents=True, exist_ok=True)
    (repo / ".xeyo" / "settings.json").write_text(
        json.dumps({"coord": {"workers": True, "backend": "file"}}), encoding="utf-8")
    return repo


def test_flag_off_refuses(tmp_path, monkeypatch):
    from cli.coord_cmd import _require_enabled

    repo = tmp_path / "off"
    repo.mkdir()
    (repo / ".xeyo").mkdir()
    (repo / ".xeyo" / "settings.json").write_text('{"coord":{"workers":false}}',
                                                  encoding="utf-8")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    with pytest.raises(SystemExit) as ei:
        _require_enabled(str(repo))
    assert ei.value.code == 2


def test_coord_run_loop_offline(tmp_path, monkeypatch):
    """两张不相交任务卡 → runner 循环（注入 scripted 写文件工厂）→ 收敛到 main。"""
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    repo = _mk_repo(tmp_path)
    root = str(repo)
    store = CoordFileStore(repo)
    planner = Planner(repo, store)
    ids = planner.plan_round([
        {"title": "w1", "scope": ["one.txt"], "brief": "写 one"},
        {"title": "w2", "scope": ["two.txt"], "brief": "写 two"},
    ], goal_id="cli-goal")["created"]
    assert len(ids) == 2

    # scripted 工厂：在 worktree 写 scope[0] 文件（不建真会话，纯验编排循环）
    def factory(task):
        def fn(p: Path) -> None:
            (p / Path(task.scope[0]).name).write_text(f"cli:{task.task_id}\n",
                                                      encoding="utf-8")
        return fn

    from cli.coord_cmd import run_coord_run

    with pytest.raises(SystemExit) as ei:
        run_coord_run(cwd=root, max_tasks=2, work_fn_factory=factory, idle_poll_sec=0.05)
    assert ei.value.code == 0

    # 两任务都 merged、main 出现两文件、历史线性
    assert store.load_task(ids[0]).status == STATUS_MERGED
    assert store.load_task(ids[1]).status == STATUS_MERGED
    assert "cli:" in git(repo, "show", "main:one.txt").stdout
    assert "cli:" in git(repo, "show", "main:two.txt").stdout
    lines = git(repo, "rev-list", "--parents", "main").stdout.strip().splitlines()
    for idx, line in enumerate(lines[:-1]):
        assert len(line.split()) == 2
