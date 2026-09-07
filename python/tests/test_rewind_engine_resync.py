"""回溯后内存态对齐（SessionPool.resync_after_rewind 契约）。

回溯 v3 热路径只重写磁盘 transcript；常驻 engine 的 ``mutable_messages``、
``_history_stash``、working sidecar（compact 游标 / C2 摘要）此前漏接，
下一轮 LLM 会看到 GUI 已不可见的被回溯回合（用户视角 =「收到没发过的消息」）。

本文件锁死对齐契约：
- 热引擎 resync：历史截到磁盘前缀 + 落盘游标/known_ids 对齐；
- 压缩/投影态复位并落盘 sidecar；
- 无引擎时 stash 清理（stash 优先于磁盘，回溯后必脏）；
- busy 窗口：置 pending 位，try_begin 在下一 turn 开始前消费；
- v3 路由：continue 提交后必须触发 resync（接线回归）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server import app as app_mod
from server.app import app
from server.session_pool import ModelConfig, SessionPool
from session.persistence import transcript_path


def _cfg() -> ModelConfig:
    return ModelConfig(
        provider="deepseek",
        api_key="k",
        base_url="https://example.com/v1",
        model="m1",
    )


def _write_transcript(sid: str, ids: list[str]) -> Path:
    path = transcript_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, mid in enumerate(ids):
        rows.append(
            {"id": mid, "role": "user" if i % 2 == 0 else "assistant", "content": f"c-{mid}"}
        )
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return path


def _truncate_transcript(sid: str, keep_ids: list[str]) -> None:
    path = transcript_path(sid)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    kept = [r for r in rows if r.get("id") in set(keep_ids)]
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept),
        encoding="utf-8",
    )


def test_resync_truncates_warm_engine_to_disk_prefix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    sid = "resync:warm"
    _write_transcript(sid, ["m1", "m2", "m3", "m4"])
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    eng = pool.get_or_create(sid, _cfg())
    assert len(eng.mutable_messages) == 4

    # 模拟 hotpath rewind continue：transcript 原子重写为保留前缀。
    _truncate_transcript(sid, ["m1", "m2"])
    assert pool.resync_after_rewind(sid) is True

    msgs = eng.mutable_messages
    assert [m.id for m in msgs] == ["m1", "m2"]
    assert eng._session.transcript_persist_index == 2
    assert eng._session.transcript_known_ids == {"m1", "m2"}
    # MessageStore 的 API 投影缓存同步失效，下一轮发给模型的历史同前缀。
    assert [row["content"] for row in eng._session.messages.as_api_messages()] == [
        "c-m1",
        "c-m2",
    ]


def test_resync_resets_compact_state_and_sidecar(tmp_path: Path, monkeypatch) -> None:
    from memory.working import hydrate as hydrate_working

    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    sid = "resync:compact"
    _write_transcript(sid, ["m1", "m2", "m3", "m4"])
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    eng = pool.get_or_create(sid, _cfg())
    snap = eng._session.working
    snap.compact_cursor = 3
    snap.c1_frozen_until = 3
    snap.c2_summary_text = "stale summary of rewound turns"
    snap.turns_since_c2 = 5
    snap.todos = [{"id": "t1", "content": "stale", "status": "pending"}]

    _truncate_transcript(sid, ["m1"])
    assert pool.resync_after_rewind(sid) is True

    assert snap.compact_cursor == 0
    assert snap.c1_frozen_until == 0
    assert snap.c2_summary_text == ""
    assert snap.turns_since_c2 == 0
    assert snap.todos == []
    # 复位已落盘：重启 hydrate 不会带回被回溯轮的压缩态。
    disk_snap = hydrate_working(sid)
    assert disk_snap.compact_cursor == 0
    assert disk_snap.c2_summary_text == ""


def test_resync_clears_stash_when_engine_absent(tmp_path: Path, monkeypatch) -> None:
    from msgtypes.message import Message

    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    sid = "resync:stash"
    _write_transcript(sid, ["m1", "m2"])
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    # 模拟 LRU 逐出：stash 持有回溯前的完整历史，磁盘已截断。
    pool._history_stash[sid] = [
        Message(role="user", content="rewound-away", id="m1"),
        Message(role="assistant", content="ghost", id="m2"),
        Message(role="user", content="ghost-q", id="m3"),
    ]

    assert pool.resync_after_rewind(sid) is True
    eng = pool.get_or_create(sid, _cfg())
    # stash 被清：重建历史只能来自截断后的磁盘（幽灵消息不得复活）。
    assert [m.id for m in eng.mutable_messages] == ["m1", "m2"]


def test_resync_while_busy_defers_to_next_turn(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    sid = "resync:busy"
    _write_transcript(sid, ["m1", "m2", "m3", "m4"])
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    eng = pool.get_or_create(sid, _cfg())

    lease = pool.try_begin(sid)
    assert lease is not None
    _truncate_transcript(sid, ["m1", "m2"])
    # busy：绝不截断进行中的回合，置 pending 位。
    assert pool.resync_after_rewind(sid) is False
    assert len(eng.mutable_messages) == 4

    pool.end(sid, lease)
    lease2 = pool.try_begin(sid)
    assert lease2 is not None
    pool.end(sid, lease2)
    # pending 已消费：新 turn 开始前历史已对齐。
    assert [m.id for m in eng.mutable_messages] == ["m1", "m2"]


def test_rewind_route_triggers_resync(monkeypatch, tmp_path: Path) -> None:
    """接线回归：POST /v1/sessions/{sid}/rewind continue 成功后必须调 resync。"""
    from tests.test_rewind_service import _build_session

    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    service, _target, ids = _build_session(tmp_path)
    app_mod._pool.set_cwd(str(tmp_path / "workspace"))

    called: list[str] = []
    monkeypatch.setattr(
        app_mod._pool, "resync_after_rewind", lambda sid: called.append(sid) or True
    )
    resp = TestClient(app).post(
        f"/v1/sessions/{service.session_id}/rewind",
        json={
            "mode": "continue",
            "target_message_id": ids["target_message_id"],
            "edited_text": "edited copy",
            "confirmed": True,
        },
    )
    assert resp.status_code == 200
    assert called == [service.session_id]
