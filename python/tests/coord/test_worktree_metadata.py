"""Independent worktree indexes still share Git administrative metadata."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
import time

import pytest

from coord.file_store import CoordFileStore
from coord.store import STATUS_REOPENED, new_task
from coord.worker_pool import WorkerPool
from coord.worktree import WorktreeError, WorktreeManager, git
from coord.worktree_metadata import metadata_guard


@pytest.mark.parametrize("second", ["create", "remove"])
def test_worktree_metadata_changes_do_not_overlap(tmp_path, monkeypatch, second):
    (tmp_path / ".git").mkdir()
    active = 0
    peak = 0
    counter_lock = threading.Lock()
    barrier = threading.Barrier(2)
    def controlled_git(repo, *args, **kwargs):
        nonlocal active, peak
        if args[:2] == ("rev-parse", "--git-common-dir"):
            return subprocess.CompletedProcess(args, 0, stdout=".git\n", stderr="")
        with counter_lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(.04)
        finally:
            with counter_lock:
                active -= 1
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr("coord.worktree.git", controlled_git)
    def work(index):
        manager = WorktreeManager(tmp_path)
        barrier.wait()
        if index == 0 or second == "create":
            manager.create(f"task_{index}", "HEAD")
        else:
            manager.remove(f"task_{index}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(work, range(2)))
    assert peak == 1, "shared Git metadata was concurrently mutated"


def test_create_failure_releases_claim_instead_of_escaping(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@local", "commit", "--allow-empty", "-m", "seed")
    store = CoordFileStore(repo)
    task = new_task("goal", "create failure", ["file.txt"])
    store.create_task(task)
    def fail_create(*args):
        raise WorktreeError("worktree add failed")
    monkeypatch.setattr(WorktreeManager, "create", fail_create)
    outcome = WorkerPool(repo, store).run_task(task.task_id, "worker", lambda path: None)
    assert not outcome.ok and "worktree add failed" in outcome.error
    assert store.load_task(task.task_id).status == STATUS_REOPENED


def test_linked_worktrees_resolve_the_same_metadata_guard(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "-c", "user.name=test", "-c", "user.email=test@local", "commit", "--allow-empty", "-m", "seed")
    manager = WorktreeManager(tmp_path)
    handle = manager.create("task_linked", "HEAD")
    try:
        primary = metadata_guard(tmp_path, git, timeout=1)
        linked = metadata_guard(handle.path, git, timeout=1)
        assert primary.path == linked.path
    finally:
        manager.remove("task_linked")
