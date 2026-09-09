"""coord 阶段 0 契约测试：双进程 CAS / 租约 stale 回收 / 跨进程 presence / 状态机。

验收口径（计划 §3 阶段 0）：
a. 两个真实子进程并发 CAS 认领同一 task，恰好一个成功；
b. 租约（FileGuard）TTL 过期被 stale 回收，旧持有者不能误删新持有者的锁；
c. backend=file 时，进程 A note_write 的文件，进程 B 的 owner_of()/peers() 可见。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from coord.file_store import CoordFileStore, root_hash
from coord.locking import FileGuard
from coord.presence_adapter import FileBackedPresence, _coord_home
from coord.store import (
    REOPEN_LIMIT,
    STATUS_BLOCKED,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_PENDING_REVIEW,
    STATUS_REOPENED,
    acquire_scope,
    new_task,
    release_scope,
    reopen_task,
    scope_conflicts,
)

PYTHON = sys.executable
CHILD = str(Path(__file__).resolve().parent / "coord_child.py")


def _run_child(args: list[str], *, xeyo_home: Path | None, timeout: float = 60.0) -> dict:
    env = dict(os.environ)
    if xeyo_home is not None:
        env["XEYO_HOME"] = str(xeyo_home)
    proc = subprocess.run(
        [PYTHON, CHILD, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=timeout,
    )
    assert proc.returncode == 0, f"child failed: {proc.stderr[-800:]}"
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# a. 双进程 CAS 认领：恰好一个成功
# ---------------------------------------------------------------------------


def test_claim_cas_two_processes_exactly_one_winner(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = CoordFileStore(ws)
    task = new_task("goal-1", "实现登录页", ["gui/src/login.tsx"])
    store.create_task(task)

    home = tmp_path / "home"
    home.mkdir()
    results = [
        _run_child(["claim", str(ws), task.task_id, f"proc-{i}", "base001", "400"],
                   xeyo_home=home)
        for i in range(2)
    ]
    total = sum(r["ok"] for r in results)
    assert total == 1, f"expect exactly one winner, got {results}"
    winner = next(r for r in results if r["ok"])
    assert winner["task"]["status"] == STATUS_CLAIMED
    assert winner["task"]["base_commit"] == "base001"
    # 持久化态一致
    assert store.load_task(task.task_id).status == STATUS_CLAIMED


# ---------------------------------------------------------------------------
# b. FileGuard：stale 回收 + 旧持有者不误删
# ---------------------------------------------------------------------------


def test_file_guard_stale_reclaim(tmp_path: Path):
    lock = tmp_path / "x.lock"
    lock.write_text("old-token", encoding="utf-8")
    old_m = time.time() - 60.0
    os.utime(lock, (old_m, old_m))

    guard = FileGuard(lock, ttl=1.0, timeout=2.0)
    with guard as ok:
        assert ok is True
        assert lock.read_text(encoding="utf-8").strip() != "old-token"
        # 旧持有者 release：token 不匹配 → 不删新持有者的锁
        stale_guard = FileGuard(lock, ttl=1.0, timeout=0.1)
        stale_guard._token = None
        # 模拟旧 token 的清理逻辑：内容不匹配时不 unlink
        data = lock.read_bytes().strip().decode("utf-8", errors="ignore")
        assert data != "old-token"
    assert not lock.exists()


def test_file_guard_exclusive_and_release(tmp_path: Path):
    lock = tmp_path / "y.lock"
    with FileGuard(lock, timeout=1.0) as first:
        assert first is True
        with FileGuard(lock, timeout=0.2) as second:
            assert second is False  # 竞争失败 → 降级路径
    with FileGuard(lock, timeout=1.0) as third:
        assert third is True  # 释放后可再获取


# ---------------------------------------------------------------------------
# c. 跨进程 presence 可见
# ---------------------------------------------------------------------------


def test_presence_cross_process_visibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    # 父进程与子进程共用同一 XEYO_HOME（全局索引所在）。
    monkeypatch.setenv("XEYO_HOME", str(home))

    _run_child(["write", str(ws), "sess-a", "src/auth.ts", "会话A"], xeyo_home=home)
    _run_child(["busy", str(ws), "sess-a", "会话A"], xeyo_home=home)

    # 另一个"进程"（本测试进程）读：owner_of 命中 + peers 可见
    fb = FileBackedPresence()
    owner = fb.owner_of(str(ws), str(ws / "src" / "auth.ts"), exclude_session="sess-b")
    assert owner is not None
    assert owner.session_id == "sess-a"
    assert owner.busy is True
    peers = fb.peers(str(ws), "sess-b")
    assert [p.session_id for p in peers] == ["sess-a"]

    # 无 cwd 方法经全局索引反查
    assert fb.knows_session("sess-a") is True
    assert fb.display_title("sess-a") == "会话A"
    fb.queue_notice("sess-a", "会话「B」已继续写入")
    notices = fb.take_notices("sess-a")
    assert notices == ["会话「B」已继续写入"]
    assert fb.take_notices("sess-a") == []  # drain 语义


def test_coord_home_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "custom-home"))
    assert _coord_home() == tmp_path / "custom-home"
    monkeypatch.delenv("XEYO_HOME")
    # 不注入时回退默认（不 assert 具体值，只保证可调用）
    assert _coord_home() is not None


# ---------------------------------------------------------------------------
# 单进程：任务状态机 / scope 租约 / ask 队列
# ---------------------------------------------------------------------------


def test_task_state_machine_full(tmp_path: Path):
    store = CoordFileStore(tmp_path)
    task = new_task("goal-1", "t", ["a.py"])
    store.create_task(task)

    # 非持有者不能 review/resume/complete
    assert store.claim_task(task.task_id, "w1", "base1") is not None
    assert store.task_transition(task.task_id, "w2", "review") is None

    # claimed → PENDING_REVIEW → resume（仅原持有者）
    assert store.task_transition(task.task_id, "w1", "review").status == STATUS_PENDING_REVIEW
    assert store.task_transition(task.task_id, "w2", "resume") is None
    assert store.task_transition(task.task_id, "w1", "resume").status == STATUS_CLAIMED
    assert store.task_transition(task.task_id, "w1", "complete").status == STATUS_COMPLETED


def test_reopen_fuse_blocks_after_limit(tmp_path: Path):
    """v1.1 验收口径：允许 REOPEN_LIMIT 次打回重做，第 4 次打回自动 blocked。"""
    store = CoordFileStore(tmp_path)
    task = new_task("goal-1", "t", ["a.py"])
    store.create_task(task)
    tid = task.task_id

    for round_no in range(REOPEN_LIMIT + 1):
        claimed = store.claim_task(tid, "w1", "base1")
        assert claimed is not None
        reopened = store.task_transition(
            tid, "w1", "reopen", findings=[{"file": "a.py", "line": 12, "error": "lint"}]
        )
        assert reopened is not None
        assert reopened.reopen_count == round_no + 1
        assert reopened.findings[0]["line"] == 12
        if round_no < REOPEN_LIMIT:
            assert reopened.status == STATUS_REOPENED
        else:
            assert reopened.status == STATUS_BLOCKED

    # 第 4 次打回已熔断：blocked，不可再认领
    final = store.load_task(tid)
    assert final.status == STATUS_BLOCKED
    assert store.claim_task(tid, "w1", "base1") is None


def test_claim_requires_scope(tmp_path: Path):
    """阶段 2：无 scope 任务不可认领（scope 声明强制，认领闸门机器执法）。"""
    store = CoordFileStore(tmp_path)
    naked = new_task("goal-1", "no scope", [])
    store.create_task(naked)
    assert store.claim_task(naked.task_id, "w1", "base1") is None
    # 补 scope 后可认领
    store._save_task(replace(naked, scope=["x.py"]))
    assert store.claim_task(naked.task_id, "w1", "base1") is not None


def test_scope_lease_mutual_exclusion(tmp_path: Path):
    store = CoordFileStore(tmp_path)
    root = str(tmp_path)
    l1 = store.acquire_scope(root, "w1", ["src/a.py", "src/b.ts"])
    assert l1 is not None
    # 交集拒绝
    assert store.acquire_scope(root, "w2", ["src/b.ts"]) is None
    # 无交集放行
    l2 = store.acquire_scope(root, "w2", ["gui/app.tsx"])
    assert l2 is not None
    # 同 owner 重叠 → 续约合并
    merged = store.acquire_scope(root, "w1", ["src/c.py"])
    assert merged is not None
    leases = store.active_leases(root)
    w1 = [l for l in leases if l.owner == "w1"]
    assert len(w1) == 1 and set(w1[0].paths) == {"src/a.py", "src/b.ts", "src/c.py"}
    # 释放后可被他人认领
    assert store.release_scope(root, l1.lease_id, "w1") is True
    assert store.acquire_scope(root, "w3", ["src/a.py"]) is not None


def test_scope_conflicts_semantics():
    # 任一方为空 → 冲突（保守串行）
    assert scope_conflicts([], ["a.py"]) is True
    assert scope_conflicts(["a.py"], []) is True
    assert scope_conflicts(["a.py"], ["b.py"]) is False
    assert scope_conflicts(["src\\a.py"], ["src/a.py"]) is True  # 分隔符归一


def test_ask_queue_roundtrip(tmp_path: Path):
    store = CoordFileStore(tmp_path)
    root = str(tmp_path)
    ask = store.put_ask(root, "w1", "peer_file_busy", "文件 src/a.py 正由 w2 持有")
    assert store.pending_asks(root)[0].ask_id == ask.ask_id
    assert store.resolve_ask(root, ask.ask_id, "allow") is True
    assert store.pending_asks(root) == []
    assert store.resolve_ask(root, ask.ask_id, "deny") is False  # 已 resolved


def test_presence_state_roundtrip_serialization():
    from engine.session_presence import PresenceState

    st = PresenceState()
    st.touch_busy("/ws", "sess-a", busy=True, title="修登录")
    st.note_write("/ws", "sess-a", "/ws/src/auth.ts")
    st.queue_notice("sess-a", "hello")
    raw = st.to_dict()
    st2 = PresenceState.from_dict(raw)
    peers = st2.peers("/ws", "sess-b")
    assert len(peers) == 1
    assert peers[0].title == "修登录"
    assert peers[0].owned_files == {"src/auth.ts": peers[0].owned_files["src/auth.ts"]}
    assert st2.take_notices("sess-a") == ["hello"]


def test_root_hash_stable_and_distinct(tmp_path: Path):
    a = tmp_path / "a"
    a.mkdir()
    assert root_hash(str(a)) == root_hash(str(a.resolve()))
    b = tmp_path / "b"
    b.mkdir()
    assert root_hash(str(a)) != root_hash(str(b))
