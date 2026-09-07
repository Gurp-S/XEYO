"""回溯第二批守卫契约：判忙双闸 / 写队列排空 / restore 串行化 /
自驱动解耦 / resync 加固 / v2 drop_engine。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from rewind.hotpath import RewindHotpath
from rewind.index import freeze_checkpoint
from server import app as app_mod
from server.app import app
from server.session_pool import ModelConfig, SessionPool
from session.persistence import safe_session_filename


def _cfg() -> ModelConfig:
    return ModelConfig(
        provider="deepseek",
        api_key="k",
        base_url="https://example.com/v1",
        model="m1",
    )


def _write_transcript(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"id": mid, "role": "user" if i % 2 == 0 else "assistant", "content": f"c-{mid}"}
        for i, mid in enumerate(ids)
    ]
    path.write_text(
        "".join(json_line(rows) for rows in rows),
        encoding="utf-8",
    )


def json_line(row: dict) -> str:
    import json

    return json.dumps(row, ensure_ascii=False) + "\n"


def test_rewind_route_409_when_turn_runner_running(monkeypatch, tmp_path: Path) -> None:
    """双闸第二道：pool 租约被 stale 回收后，活跃 turn 仍能挡住回溯。"""
    from tests.test_rewind_service import _build_session

    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    service, _target, ids = _build_session(tmp_path)
    app_mod._pool.set_cwd(str(tmp_path / "workspace"))

    class _FakeRunner:
        def is_running(self, session_id: str) -> bool:
            return True

    monkeypatch.setattr(
        "engine.turn_runner.get_turn_runner", lambda: _FakeRunner()
    )
    resp = TestClient(app).post(
        f"/v1/sessions/{service.session_id}/rewind",
        json={
            "mode": "continue",
            "target_message_id": ids["target_message_id"],
            "edited_text": "x",
            "confirmed": True,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "session_busy"


def test_rewind_flushes_transcript_writer(monkeypatch, tmp_path: Path) -> None:
    """回溯改写 transcript 前必须排空异步写队列（B 契约的接线回归）。"""
    from tests.test_rewind_service import _build_session

    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    service, _target, ids = _build_session(tmp_path)
    app_mod._pool.set_cwd(str(tmp_path / "workspace"))

    calls: list[str] = []
    import importlib

    rt = importlib.import_module("session.record_transcript")
    real_flush = rt.flush_pending_sync
    monkeypatch.setattr(
        rt,
        "flush_pending_sync",
        lambda timeout=5.0: calls.append("flush") or real_flush(timeout=0.1),
    )
    resp = TestClient(app).post(
        f"/v1/sessions/{service.session_id}/rewind",
        json={
            "mode": "continue",
            "target_message_id": ids["target_message_id"],
            "edited_text": "x",
            "confirmed": True,
        },
    )
    assert resp.status_code == 200
    # 路由与 hotpath 各排空一次（hotpath 是公共 API，直调方也有保障）。
    assert calls and calls[0] == "flush"


def test_rewind_detaches_goal_and_inbox(monkeypatch, tmp_path: Path) -> None:
    """continue 提交后：goal driver drop + inbox 队列清空（自驱动解耦）。

    2026-09-05：goal 侧从 disarm 升级为 drop_session（连 per-session 内存态
    一起清），并新增合成轮请求环境清理。
    """
    from tests.test_rewind_service import _build_session

    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    service, _target, ids = _build_session(tmp_path)
    app_mod._pool.set_cwd(str(tmp_path / "workspace"))

    dropped: list[str] = []
    env_cleared: list[str] = []

    class _FakeDriver:
        def drop_session(self, session_id: str) -> None:
            dropped.append(session_id)

    class _FakeInbox:
        def drop_session(self, session_id: str) -> None:
            dropped.append(session_id)

    monkeypatch.setattr(
        "server.goal_round_driver.get_goal_round_driver", lambda: _FakeDriver()
    )
    monkeypatch.setattr(
        "server.inbox_registry.get_inbox_registry", lambda: _FakeInbox()
    )
    monkeypatch.setattr(
        "server.synthetic_round.clear_request_env",
        lambda session_id: env_cleared.append(session_id),
    )
    resp = TestClient(app).post(
        f"/v1/sessions/{service.session_id}/rewind",
        json={
            "mode": "continue",
            "target_message_id": ids["target_message_id"],
            "edited_text": "x",
            "confirmed": True,
        },
    )
    assert resp.status_code == 200
    assert dropped == [service.session_id, service.session_id]
    assert env_cleared == [service.session_id]
    assert resp.json()["memory_resync"] is True


def test_restore_workers_serialize(monkeypatch, tmp_path: Path) -> None:
    """同会话两个后台 restore worker 必须串行（无并发写工作区窗口）。"""
    sessions = tmp_path / "sessions"
    snapshots = tmp_path / "snapshots"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sid = "s:serialize"
    from rewind.snapshot import SnapshotStore

    store = SnapshotStore(sid, root=snapshots, enabled=True)
    transcript = sessions / f"{safe_session_filename(sid)}.jsonl"
    _write_transcript(
        transcript, ["m1", "m2", "m3", "m4", "m5"]
    )
    cp = freeze_checkpoint(sid, "m3", snapshots=store, sessions_dir=sessions)

    hot = RewindHotpath(
        sid, sessions_dir=sessions, snapshots=store, workspace_root=workspace
    )
    timeline: list[tuple[str, float]] = []
    gate = threading.Event()

    def fake_restore(self, checkpoint_id: str):
        tag = checkpoint_id
        timeline.append(("enter", tag, time.monotonic()))
        if len(timeline) == 1:
            gate.wait(timeout=2.0)
        timeline.append(("exit", tag, time.monotonic()))
        return (
            {
                "restored": [],
                "deleted": [],
                "unchanged": [],
                "skipped_dirty": [],
                "failed": [],
            },
            [],
        )

    monkeypatch.setattr(RewindHotpath, "_restore_checkpoint_files", fake_restore)

    r1 = hot.rewind(
        mode="restore",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        confirmed=True,
    )
    # 等 worker1 进入临界区并被 gate 挡住。
    deadline = time.time() + 5
    while time.time() < deadline and not timeline:
        time.sleep(0.02)
    assert len(timeline) == 1

    r2 = hot.rewind(
        mode="restore",
        target_message_id="m5",
        checkpoint_id=cp.checkpoint_id,
        confirmed=True,
    )
    # worker2 不得在 worker1 退出前进入（串行化的核心断言）。
    time.sleep(0.3)
    assert len(timeline) == 1

    gate.set()
    deadline = time.time() + 5
    while time.time() < deadline:
        s1 = hot.get_event(r1.rewind_id)
        s2 = hot.get_event(r2.rewind_id)
        if (s1 or {}).get("status") in {"committed", "partial"} and (s2 or {}).get(
            "status"
        ) in {"committed", "partial"}:
            break
        time.sleep(0.02)

    enters = [t for (kind, _t, t) in timeline if kind == "enter"]
    exits = [t for (kind, _t, t) in timeline if kind == "exit"]
    assert len(enters) == 2 and len(exits) == 2
    # 串行：第二个 worker 的 enter 不得早于第一个的 exit。
    first_exit, second_enter = min(exits), max(enters)
    assert second_enter >= first_exit - 1e-6


def test_resync_skips_engine_replace_when_persistence_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    """持久化关闭时磁盘 transcript 不是权威：严禁用它清空引擎记忆。"""
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    from msgtypes.message import Message

    pool.get_or_create(
        "s:disabled",
        _cfg(),
        initial_messages=[Message(role="user", content="keep me", id="m1")],
    )
    import session.persistence as persistence

    monkeypatch.setattr(
        persistence, "is_session_persistence_disabled", lambda: True
    )
    assert pool.resync_after_rewind("s:disabled") is False
    eng = pool.get_if_present("s:disabled")
    assert eng is not None
    assert [m.content for m in eng.mutable_messages] == ["keep me"]


def test_pool_drop_engine_keeps_cwd_pin(tmp_path: Path) -> None:
    """v2 on_commit 语义：丢引擎但保留 cwd pin / preset / todo store。"""
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    pool.get_or_create("s:pin", _cfg())
    assert pool.session_cwd("s:pin") is not None

    assert pool.drop_engine("s:pin") is True
    assert pool.get_if_present("s:pin") is None
    # pin 保留：下次请求不带 cwd 也不会换仓。
    assert pool.session_cwd("s:pin") is not None
    assert pool.drop_engine("s:pin") is False
