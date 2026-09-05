from __future__ import annotations

import json
import multiprocessing
import os
import time

from engine.workspace_lock import LeaseBusyError, WorkspaceLock


def _try_acquire(workspace: str, result_queue) -> None:
    lock = WorkspaceLock(workspace, owner="child", ttl_seconds=10)
    try:
        lock.acquire()
    except LeaseBusyError:
        result_queue.put("busy")
    else:
        result_queue.put("acquired")
        lock.release()


def test_workspace_lock_rejects_second_process(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lock = WorkspaceLock(workspace, owner="parent", ttl_seconds=10)
    lock.acquire()
    try:
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        process = context.Process(target=_try_acquire, args=(str(workspace), result_queue))
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert result_queue.get(timeout=2) == "busy"
    finally:
        lock.release()


def test_workspace_lock_reclaims_expired_lease(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lock = WorkspaceLock(workspace, owner="new-owner", ttl_seconds=10)
    lock.lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock.lock_file.write_text(
        json.dumps(
            {
                "lease_id": "expired",
                "owner": "old-owner",
                "acquired_at": time.time() - 20,
                "expires_at": time.time() - 10,
            }
        ),
        encoding="utf-8",
    )
    
    # 还必须写入 sidecar 心跳文件才能被正确解析，
    # 并被视为有效（但已过期）租约而非损坏。
    heartbeat = lock._heartbeat_path("expired")
    heartbeat.write_bytes(b"heartbeat\n")
    # 人为把心跳文件改老，使其过期
    os.utime(heartbeat, (time.time() - 20, time.time() - 20))

    lease = lock.acquire()
    try:
        assert lease.owner == "new-owner"
    finally:
        lock.release()


def test_reclaim_stale_if_expired(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lock = WorkspaceLock(workspace, owner="reclaim", ttl_seconds=5)
    lock.lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock.lock_file.write_text(
        json.dumps(
            {
                "lease_id": "expired",
                "owner": "recovery_dead",
                "acquired_at": time.time() - 20,
            }
        ),
        encoding="utf-8",
    )
    heartbeat = lock._heartbeat_path("expired")
    heartbeat.write_bytes(b"heartbeat\n")
    os.utime(heartbeat, (time.time() - 20, time.time() - 20))
    assert lock.reclaim_stale_if_expired() is True
    assert not lock.lock_file.exists()
