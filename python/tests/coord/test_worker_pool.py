"""coord 阶段 1 契约测试：worktree 生命周期 / Reconciler 三路合并 / worker 池闭环。

验收口径（计划 §3 阶段 1）：
a. worktree 生命周期：create(base) → commit → remove（即弃，分支同删）；
b. 交叉用例（v1.1 硬要求）：A 删文件 X、B 改文件 X → 三路合并正确判定
   后提交者为冲突 → reopen 且 base_commit 写回最新 main head → 基于新
   基线重做后收敛，主分支历史线性；
c. reopen 冲突熔断：第 REOPEN_LIMIT 次打回转 blocked；
d. 50 worker 并行压测：0 次 index.lock 事故，收敛后历史线性、内容全对。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from coord.file_store import CoordFileStore
from coord.reconciler import Reconciler
from coord.store import (
    REOPEN_LIMIT,
    STATUS_MERGED,
    STATUS_READY_TO_MERGE,
    STATUS_REOPENED,
    STATUS_BLOCKED,
    new_task,
)
from coord.worker_pool import WorkerPool
from coord.worktree import WorktreeManager, git, worktree_path


# -- 环境 helpers ------------------------------------------------------------

def _git(cwd: Path, *args: str, check: bool = True):
    return git(cwd, *args, check=check)


def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "coord-test")
    _git(repo, "config", "user.email", "coord@test.local")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    return repo


def _mk_task(store: CoordFileStore, title: str, scope: list[str]) -> str:
    t = new_task("g1", title, scope)
    store.create_task(t)
    return t.task_id


def _main_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _assert_linear(repo: Path) -> list[str]:
    """主分支历史线性：除 root（rev-list 末行）外每个 commit 恰 1 个 parent。"""
    lines = _git(repo, "rev-list", "--parents", "main").stdout.strip().splitlines()
    commits: list[str] = []
    for idx, line in enumerate(lines):
        parts = line.split()
        commits.append(parts[0])
        if idx < len(lines) - 1:  # 末行是 root（无 parent），豁免
            assert len(parts) == 2, f"non-linear commit {parts[0][:12]} parents={len(parts) - 1}"
    return commits


def _submit_state(store: CoordFileStore, task_id: str) -> str:
    t = store.load_task(task_id)
    assert t is not None
    return t.status


# -- a. worktree 生命周期 -----------------------------------------------------

def test_worktree_lifecycle_commit_and_remove(tmp_path):
    repo = _mk_repo(tmp_path)
    base = _main_head(repo)
    wm = WorktreeManager(repo)
    handle = wm.create("task_lifecyc", base)
    assert handle.path.exists()
    assert (handle.path / "seed.txt").read_text(encoding="utf-8") == "seed\n"

    (handle.path / "a.txt").write_text("hello\n", encoding="utf-8")
    head = wm.commit_all(handle, "add a.txt")
    assert head is not None and len(head) == 40

    # 空改动 → committed=None
    assert wm.commit_all(handle, "noop") is None

    wm.remove("task_lifecyc")
    assert not handle.path.exists()
    # 分支同删：rev-parse 该分支应失败
    assert _git(repo, "rev-parse", "--verify", handle.branch, check=False).returncode != 0


# -- b. 交叉用例：A 删 X / B 改 X（v1.1 硬要求） -------------------------------

def test_cross_modify_delete_reopen_and_redo(tmp_path):
    repo = _mk_repo(tmp_path)
    (repo / "shared.txt").write_text("v0\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add shared")

    store = CoordFileStore(repo)
    ta = _mk_task(store, "A delete shared", ["shared.txt"])
    tb = _mk_task(store, "B edit shared", ["shared.txt"])

    def work_del(p: Path) -> None:
        _git(p, "rm", "-f", "shared.txt")

    def work_edit(p: Path) -> None:
        (p / "shared.txt").write_text("v0\nb-edit\n", encoding="utf-8")

    # 两 worker 均在收敛前上交；顺序提交固定 A 先收敛（reconciler 按 updated_at 排序，
    # 并行形态由 50-worker 压测用例承担）。A 删 X 先 merged → B 改 X 必判 modify/delete 冲突。
    oa = WorkerPool(repo, CoordFileStore(repo)).run_task(ta, "wA", work_del)
    ob = WorkerPool(repo, CoordFileStore(repo)).run_task(tb, "wB", work_edit)
    assert oa.ok and ob.ok, f"{oa.error} / {ob.error}"
    assert store.load_task(ta).status == STATUS_READY_TO_MERGE
    assert store.load_task(tb).status == STATUS_READY_TO_MERGE

    # 串行收敛：A(删) merged，B(改) 三路合并判冲突 reopen
    rec = Reconciler(repo, store)
    report = rec.reconcile_ready()
    assert len(report["merged"]) == 1, report
    assert len(report["reopened"]) == 1, report

    merged_id = report["merged"][0]["task_id"]
    reopened_id = report["reopened"][0]["task_id"]
    assert merged_id == ta and reopened_id == tb, report
    assert store.load_task(merged_id).status == STATUS_MERGED

    rt = store.load_task(reopened_id)
    assert rt.status == STATUS_REOPENED
    assert rt.reopen_count == 1
    # base_commit 写回最新 main head（v1.1：重放对齐新基线）
    assert rt.base_commit == _main_head(repo)
    assert any(f.get("error") == "rebase_conflict" for f in rt.findings)
    # worktree 即弃
    assert not worktree_path(repo, reopened_id).exists()

    # 基于新基线重放意图（避开已删文件）→ 收敛成功
    def work_redo(p: Path) -> None:
        (p / "other.txt").write_text("redone\n", encoding="utf-8")

    out = WorkerPool(repo, store).run_task(reopened_id, "wB2", work_redo)
    assert out.ok, out.error
    report2 = rec.reconcile_ready()
    assert report2["merged"] and report2["merged"][0]["task_id"] == reopened_id, report2

    # 终态：main 无 shared.txt（删除语义保留）、有 other.txt、历史线性
    assert _git(repo, "cat-file", "-e", "main:shared.txt", check=False).returncode != 0
    assert _git(repo, "cat-file", "-e", "main:other.txt", check=False).returncode == 0
    assert store.load_task(reopened_id).status == STATUS_MERGED
    _assert_linear(repo)
    assert not (repo / ".git" / "index.lock").exists()


# -- c. 冲突打回熔断 ----------------------------------------------------------

def test_reopen_conflict_fuse(tmp_path):
    repo = _mk_repo(tmp_path)
    store = CoordFileStore(repo)
    tid = _mk_task(store, "always conflicts", ["seed.txt"])
    rec = Reconciler(repo, store)

    def work(p: Path, i: int = 0) -> None:
        (p / "seed.txt").write_text(f"worker-{i}\n", encoding="utf-8")

    for i in range(REOPEN_LIMIT):
        # worker 基于当前 main 干活并上交
        out = WorkerPool(repo, store).run_task(tid, f"w{i}", lambda p, i=i: work(p, i))
        assert out.ok, out.error
        # reconcile 之前 main 改同一文件 → 三路合并必然冲突
        (repo / "seed.txt").write_text(f"main-{i}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", f"main moves {i}")

        report = rec.reconcile_ready()
        if i < REOPEN_LIMIT - 1:
            assert store.load_task(tid).status == STATUS_REOPENED, report
        else:
            assert store.load_task(tid).status == STATUS_BLOCKED, report
            assert len(report["blocked"]) == 1


# -- submit 前置校验 ----------------------------------------------------------

def test_submit_requires_claim(tmp_path):
    repo = _mk_repo(tmp_path)
    store = CoordFileStore(repo)
    tid = _mk_task(store, "never claimed", ["y.txt"])
    assert store.submit_result(tid, "w0", "coord/task/whatever") is None


# -- d. 50 worker 并行压测 ----------------------------------------------------

@pytest.mark.timeout(600)
def test_worker_pool_50_parallel_zero_index_lock(tmp_path):
    repo = _mk_repo(tmp_path)
    store = CoordFileStore(repo)
    n = 50
    ids = [_mk_task(store, f"task {i}", [f"file_{i}.txt"]) for i in range(n)]

    def one(i: int):
        # 每线程独立 store/pool 实例（模拟独立进程，coord 状态共享在文件层）
        pool = WorkerPool(repo, CoordFileStore(repo))
        return pool.run_task(ids[i], f"w{i}",
                             lambda p, i=i: (p / f"file_{i}.txt").write_text(f"content-{i}\n",
                                                                            encoding="utf-8"))

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=10) as ex:
        outcomes = list(ex.map(one, range(n)))
    t_run = time.perf_counter() - t0
    bad = [o.error for o in outcomes if not o.ok]
    assert not bad, f"{len(bad)} workers failed: {bad[:3]}"
    assert all(o.committed for o in outcomes)

    t1 = time.perf_counter()
    report = Reconciler(repo, store).reconcile_ready()
    t_rec = time.perf_counter() - t1

    assert len(report["merged"]) == n, report
    assert not report["reopened"] and not report["blocked"], report
    # 收敛后：main 线性、50 个文件内容全对、无 index.lock 残留
    commits = _assert_linear(repo)
    assert len(commits) >= n + 1  # root(=seed) + 50 个 worker commit
    for i in range(n):
        blob = _git(repo, "show", f"main:file_{i}.txt").stdout
        assert blob == f"content-{i}\n", f"file_{i} content mismatch"
    assert not (repo / ".git" / "index.lock").exists()
    assert not report["skipped"]

    print(f"\n[stage1 bench] workers=50 run={t_run:.1f}s reconcile={t_rec:.1f}s "
          f"total={time.perf_counter() - t0:.1f}s linear_commits={len(commits)}")
