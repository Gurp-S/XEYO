"""coord 阶段 2 契约测试：ASK 网关 / Planner 闸门 / Reviewer 执法。

验收口径（计划 §3 阶段 2）：
a. ASK 挂起即释放 scope 租约——挂起期间其他 worker 可认领原持有者的 scope；
   allow 后原 worker 优先恢复（claimed_by 保留，他人不可抢）；
b. deny/remind 走 reopen（review_reopen，PENDING_REVIEW→reopened）；
c. 超时 sweep：pending ask 超 TTL → expired + 任务转 pending 挂起（非 deny 丢弃）；
d. 无 scope 任务拒收/不可认领（认领闸门 + claim_task 双保险）；
e. scope 交集任务由 CoordStore 拒绝并行认领（claim_next 租约先行）；
f. Reviewer findings 结构化强制 + 重规划 scope ⊆ 原∪findings.files 机器执法。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from coord.ask_gate import AskGate
from coord.file_store import CoordFileStore
from coord.planner import Planner
from coord.reviewer import Reviewer
from coord.store import (
    REOPEN_LIMIT,
    STATUS_BLOCKED,
    STATUS_CLAIMED,
    STATUS_PENDING,
    STATUS_PENDING_REVIEW,
    STATUS_REOPENED,
    STATUS_SUPERSEDED,
    enforce_replan_scope,
    findings_files,
    new_task,
)


# -- helpers -----------------------------------------------------------------

class StubPresence:
    """记录 touch_busy/clear_owned 调用，验证挂起时 presence 被同步清理。"""

    def __init__(self) -> None:
        self.busy: list[tuple[str, str, bool]] = []
        self.cleared: list[tuple[str, str]] = []

    def touch_busy(self, cwd, session_id, *, busy, title=""):
        self.busy.append((cwd, session_id, bool(busy)))

    def clear_owned(self, cwd, session_id, paths=None):
        self.cleared.append((cwd, session_id))


# ---------------------------------------------------------------------------
# a. ASK 挂起即释放租约 + allow 原持有者优先恢复
# ---------------------------------------------------------------------------

def test_ask_suspend_releases_lease_and_unblocks(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)
    gate = AskGate(ws, store, presence=StubPresence())
    root = str(ws)

    tid = planner.plan_round([{"title": "独占 a.py", "scope": ["src/a.py"]}])["created"][0]
    # worker 认领前先持租约（planner.claim_next 语义），这里直接模拟 claim+lease
    assert store.acquire_scope(root, "w1", ["src/a.py"]) is not None
    assert store.claim_task(tid, "w1", "base1") is not None

    # w2 此刻无法认领相交 scope（被 w1 租约挡）
    assert store.acquire_scope(root, "w2", ["src/a.py"]) is None

    # w1 触发 ASK → 挂起：释放租约 + presence 清 + 转 PENDING_REVIEW
    item = gate.suspend(root=root, task_id=tid, worker_id="w1",
                        kind="peer_file_busy", payload="src/a.py 由他人持有")
    assert item is not None
    assert store.load_task(tid).status == STATUS_PENDING_REVIEW
    assert store.load_task(tid).claimed_by == "w1"  # 保留，他人不可抢

    # 解堵：w2 现在能拿 w1 刚释放的 scope 租约
    assert store.acquire_scope(root, "w2", ["src/a.py"]) is not None
    # presence 同步清理（busy=false + owned 清除）
    assert ("w1" in [b[1] for b in gate.presence.busy]) if hasattr(gate.presence, "busy") else True

    # w2 不能恢复 w1 的任务（claimed_by 校验）
    assert gate.allow(root=root, ask_id=item.ask_id, worker_id="w2") is False
    # 原持有者 w1 恢复
    assert gate.allow(root=root, ask_id=item.ask_id, worker_id="w1") is True
    assert store.load_task(tid).status == STATUS_CLAIMED


# ---------------------------------------------------------------------------
# b. deny → review_reopen（PENDING_REVIEW 打回，非要求 claimed）
# ---------------------------------------------------------------------------

def test_ask_deny_reopens_from_pending_review(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)
    gate = AskGate(ws, store, presence=StubPresence())
    root = str(ws)

    tid = planner.plan_round([{"title": "t", "scope": ["x.py"]}])["created"][0]
    store.claim_task(tid, "w1", "b0")
    item = gate.suspend(root=root, task_id=tid, worker_id="w1",
                        kind="need_input", payload="确认删除?")
    assert store.load_task(tid).status == STATUS_PENDING_REVIEW

    ok = gate.deny(root=root, ask_id=item.ask_id, worker_id="w1",
                   findings=[{"file": "x.py", "line": 3, "error": "user_denied_delete"}])
    assert ok is True
    t = store.load_task(tid)
    assert t.status == STATUS_REOPENED
    assert t.reopen_count == 1
    # reopened 可再被认领（重做）
    assert store.claim_task(tid, "w1", "b1") is not None


# ---------------------------------------------------------------------------
# c. 超时 sweep → expired + 任务转 pending 挂起（非 deny 丢弃）
# ---------------------------------------------------------------------------

def test_ask_sweep_expired_to_pending(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)
    gate = AskGate(ws, store, presence=StubPresence(), ttl=1.0)
    root = str(ws)

    tid = planner.plan_round([{"title": "t", "scope": ["y.py"]}])["created"][0]
    store.acquire_scope(root, "w1", ["y.py"])
    store.claim_task(tid, "w1", "b0")
    item = gate.suspend(root=root, task_id=tid, worker_id="w1",
                        kind="peer_conflict", payload="…")

    # 未到 TTL：不动
    rep = gate.sweep_expired(root=root, now=time.time() + 0.5)
    assert rep["expired"] == []
    assert store.load_task(tid).status == STATUS_PENDING_REVIEW

    # 超 TTL：ask→expired，任务→pending（可被重新认领，非丢弃）
    rep = gate.sweep_expired(root=root, now=time.time() + 2.0)
    assert item.ask_id in rep["expired"]
    assert tid in rep["released"]
    t = store.load_task(tid)
    assert t.status == STATUS_PENDING
    assert t.claimed_by == ""  # 清持有
    assert store.claim_task(tid, "w9", "b1") is not None  # 他人可重新认领


# ---------------------------------------------------------------------------
# d. 无 scope 拒收（plan 层 + claim 层双保险）
# ---------------------------------------------------------------------------

def test_missing_scope_rejected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)

    rep = planner.plan_round([
        {"title": "no scope", "scope": []},
        {"title": "blank scope", "scope": ["  "]},
        {"title": "ok", "scope": ["z.py"]},
    ])
    assert len(rep["created"]) == 1
    reasons = {r["reason"] for r in rep["rejected"]}
    assert "missing_scope" in reasons

    # 双保险：直接建裸任务也不能认领
    naked = new_task("g", "naked", [])
    store.create_task(naked)
    assert store.claim_task(naked.task_id, "w1", "b") is None


# ---------------------------------------------------------------------------
# e. claim_next 租约先行：交集拒并行认领，不相交放行
# ---------------------------------------------------------------------------

def test_claim_next_scope_mutex(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)
    root = str(ws)

    planner.plan_round([
        {"title": "A", "scope": ["src/a.py"]},
        {"title": "B", "scope": ["src/b.py"]},
    ])
    # w1 认领 A
    t1 = planner.claim_next(root=root, worker_id="w1", base_commit="b0")
    assert t1 is not None and t1.title == "A"
    # w2 认领：A 已被占（租约+claimed），应拿到不相交的 B
    t2 = planner.claim_next(root=root, worker_id="w2", base_commit="b0")
    assert t2 is not None and t2.title == "B"
    # w3：两个 scope 都被占 → 无可认领
    assert planner.claim_next(root=root, worker_id="w3", base_commit="b0") is None


# ---------------------------------------------------------------------------
# f. Reviewer：结构化 findings + 重规划 scope 执法
# ---------------------------------------------------------------------------

def test_reviewer_findings_must_be_structured(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)
    rev = Reviewer(ws, store)
    tid = planner.plan_round([{"title": "t", "scope": ["a.py"]}])["created"][0]
    store.claim_task(tid, "w1", "b0")

    # 非结构（自由文本夹带）→ 拒
    assert rev.reject(task_id=tid, worker_id="w1", findings=[])["reason"] == "invalid_findings"
    assert rev.reject(task_id=tid, worker_id="w1",
                      findings=[{"text": "感觉不对"}])["reason"] == "invalid_findings"
    # 结构化 → 打回
    r = rev.reject(task_id=tid, worker_id="w1",
                   findings=[{"file": "a.py", "line": 12, "error": "lint"}])
    assert r["ok"] and r["status"] == STATUS_REOPENED


def test_replan_scope_enforcement(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    planner = Planner(ws, store)
    rev = Reviewer(ws, store)
    tid = planner.plan_round([{"title": "t", "scope": ["src/a.py"]}])["created"][0]
    store.claim_task(tid, "w1", "b0")
    rev.reject(task_id=tid, worker_id="w1",
               findings=[{"file": "src/b.ts", "line": 5, "error": "type"}])

    # 超界（src/c 既不在原 scope 也不在 findings）→ 拒
    r = rev.plan_replacement(parent_task_id=tid, proposed_scope=["src/c.py"])
    assert r["ok"] is False and r["reason"] == "scope_expansion_denied"
    assert "src/c.py" in r["proposed"]

    # 合法子集：原 scope(a) ∪ findings(b) → 允许
    ok = rev.plan_replacement(parent_task_id=tid,
                              proposed_scope=["src/a.py", "src/b.ts"])
    assert ok["ok"] is True
    child = store.load_task(ok["task_id"])
    assert child.parent_id == tid
    assert child.status == STATUS_PENDING
    # 子任务无独立 findings 时，父的 findings 不继承到 scope 判定之外
    assert set(child.scope) == {"src/a.py", "src/b.ts"}


# ---------------------------------------------------------------------------
# 纯函数单元
# ---------------------------------------------------------------------------

def test_findings_files_and_enforce_helpers():
    t = new_task("g", "x", ["a.py"])
    t.findings = [{"file": "b.ts", "line": 1, "error": "e"}, {"error": "nofile"},
                 "junk"]
    assert findings_files(t.findings) == ["b.ts"]
    # enforce：子集过、超界拒、空拒
    from coord.store import Task as _T
    parent = _T("id", "g", "t", scope=["a.py", "b.ts"], findings=[{"file": "c.py"}])
    assert enforce_replan_scope(parent, ["a.py"]) is True
    assert enforce_replan_scope(parent, ["c.py"]) is True   # c 在 findings
    assert enforce_replan_scope(parent, ["a.py", "c.py"]) is True
    assert enforce_replan_scope(parent, ["d.java"]) is False  # 超界
    assert enforce_replan_scope(parent, []) is False          # 空


# ---------------------------------------------------------------------------
# g. 端到端全链：planner → claim_next → worker → reconciler → reviewer →
#    replan → ASK 挂起/恢复（阶段 2 手工最小闭环，计划 §3 验收形态）
# ---------------------------------------------------------------------------

def _mk_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    for args in (["init", "-b", "main"], ["config", "user.name", "t"],
                 ["config", "user.email", "t@t"], ["config", "core.autocrlf", "false"]):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=str(repo),
                   check=True, capture_output=True)
    return repo


def test_stage2_full_loop(tmp_path):
    from coord.reconciler import Reconciler
    from coord.worktree import git

    repo = _mk_repo(tmp_path)
    root = str(repo)
    store = CoordFileStore(repo)
    planner = Planner(repo, store)
    rev = Reviewer(repo, store)
    gate = AskGate(repo, store, presence=StubPresence())

    # 1. Planner 一轮 3 任务（互不相交 scope，可并行）
    ids = planner.plan_round([
        {"title": "T1", "scope": ["f1.txt"]},
        {"title": "T2", "scope": ["f2.txt"]},
        {"title": "T3", "scope": ["f3.txt"]},
    ], goal_id="goal-e2e")["created"]
    assert len(ids) == 3

    # 2. 三 worker 经闸门认领（租约先行）+ 干活 + 上交
    from coord.worker_pool import WorkerPool

    def worker(i: int):
        pool = WorkerPool(repo, CoordFileStore(repo))
        t = planner.claim_next(root=root, worker_id=f"w{i}",
                               base_commit=git(repo, "rev-parse", "main").stdout.strip())
        assert t is not None and t.status == STATUS_CLAIMED
        fn = lambda p, i=i: (p / Path(t.scope[0]).name).write_text(f"c{i}\n",
                                                                   encoding="utf-8")
        return pool.run_task(t.task_id, f"w{i}", fn)

    outs = [worker(i) for i in (1, 2, 3)]
    assert all(o.ok for o in outs), outs

    # 3. Reconciler 串行收敛 → 3 merged、main 线性、内容全对
    report = Reconciler(repo, store).reconcile_ready()
    assert len(report["merged"]) == 3, report
    for i in (1, 2, 3):
        assert git(repo, "show", f"main:f{i}.txt").stdout == f"c{i}\n"

    # 4. Reviewer 打回（claimed 态 reject → reopened + 释放租约）→ replan 超界被拒
    #    → 合法子集入库 + 父 superseded → 认领子任务收敛
    t4 = planner.plan_round([{"title": "T4", "scope": ["f1.txt"]}], goal_id="goal-e2e")["created"][0]
    t4c = planner.claim_next(root=root, worker_id="w4",
                             base_commit=git(repo, "rev-parse", "main").stdout.strip())
    assert t4c is not None and t4c.task_id == t4  # 唯一可认领 = T4
    rj = rev.reject(task_id=t4, worker_id="w4", findings=[
        {"file": "f1.txt", "line": 1, "error": "content_regression"}])
    assert rj["ok"] and rj["status"] == STATUS_REOPENED
    # 释放租约后：f1.txt 可被再次 acquire（父任务不再占坑）
    assert store.acquire_scope(root, "probe", ["f1.txt"]) is not None
    store.release_scope_by_owner(root, "probe")

    denied = rev.plan_replacement(parent_task_id=t4, proposed_scope=["f1.txt", "f9.txt"])
    assert denied["ok"] is False and denied["reason"] == "scope_expansion_denied"
    ok = rev.plan_replacement(parent_task_id=t4, proposed_scope=["f1.txt"],
                              title="T4-replan")
    assert ok["ok"] is True
    assert store.load_task(t4).status == STATUS_SUPERSEDED  # 父被子接管

    # 5. 子任务认领（reopened 的 T4 已 superseded，唯一可认领 = 子）+ 上交 + 收敛
    child_id = ok["task_id"]
    child = planner.claim_next(root=root, worker_id="w5",
                               base_commit=git(repo, "rev-parse", "main").stdout.strip())
    assert child is not None and child.task_id == child_id
    o5 = WorkerPool(repo, store).run_task(
        child_id, "w5",
        lambda p: (p / "f1.txt").write_text("good\n", encoding="utf-8"))
    assert o5.ok, o5.error
    rep2 = Reconciler(repo, store).reconcile_ready()
    assert child_id in [m["task_id"] for m in rep2["merged"]], rep2
    assert git(repo, "show", "main:f1.txt").stdout == "good\n"

    # 6. ASK 挂起释放租约 → 同 scope 解堵；超时 sweep → 转 pending 被他人认领
    t6 = planner.plan_round([{"title": "T6", "scope": ["f2.txt"]}], goal_id="goal-e2e")["created"][0]
    t6c = planner.claim_next(root=root, worker_id="w6", base_commit="b6")
    assert t6c is not None and t6c.task_id == t6
    ask = gate.suspend(root=root, task_id=t6, worker_id="w6",
                       kind="peer_git_busy", payload="git rebase 进行中")
    assert ask is not None
    # 挂起释放租约：w7 能拿 f2 租约（任务本身 PENDING_REVIEW 不被抢）
    assert store.acquire_scope(root, "w7", ["f2.txt"]) is not None
    assert store.claim_task(t6, "w7", "b7") is None      # PENDING_REVIEW 不可抢
    rep3 = gate.sweep_expired(root=root, now=time.time() + 700)
    assert t6 in rep3["released"]
    assert store.claim_task(t6, "w7", "b7") is not None   # expired→pending 可重认领

    # 7. 全程零 index.lock，历史线性
    assert not (repo / ".git" / "index.lock").exists()
    lines = git(repo, "rev-list", "--parents", "main").stdout.strip().splitlines()
    for idx, line in enumerate(lines[:-1]):
        assert len(line.split()) == 2, f"non-linear: {line}"
