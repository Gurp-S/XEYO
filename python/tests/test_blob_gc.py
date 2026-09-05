"""Blob GC · 全局可达性回收单测。

覆盖设计 §36 §9.1 的几项安全性质：
- 跨会话共享 blob 不误删（全局可达性）；
- 未超预算不删、dry-run 只报告；
- 超预算且启用时才按 mtime 最旧优先删除不可达 blob。
"""

from __future__ import annotations

import json
from pathlib import Path

from rewind.blob_gc import (
    collect_reachable_blobs,
    garbage_collect,
    list_snapshot_blobs,
    retained_checkpoint_ids,
    retained_turn_ids,
    snapshot_root,
)
from rewind.index import get_checkpoint_anchor, mark_checkpoint_anchor


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def _put_blob(root: Path, content: str) -> str:
    import hashlib

    data = content.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    target = root / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return digest


def test_reachable_collected_from_journals(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snap = tmp_path / "snapshots"
    sid = "sess_a"
    a = _put_blob(snap, "reachable-a")
    b = _put_blob(snap, "unreferenced-b")

    # operations.jsonl 引用 a（before_hash/after_hash 都算可达）。
    _write_jsonl(
        sessions / sid / "operations.jsonl",
        [
            {"operation_id": "op1", "before_hash": a, "after_hash": a},
            {"operation_id": "op2", "before_hash": None, "after_hash": None},
        ],
    )
    # checkpoints.jsonl 也引用 a。
    _write_jsonl(
        sessions / sid / "checkpoints.jsonl",
        [{"checkpoint_id": "cp1", "entries": {"/f": a}}],
    )

    reachable = collect_reachable_blobs(sessions)
    assert a in reachable
    assert b not in reachable


def test_cross_session_shared_blob_survives(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snap = tmp_path / "snapshots"
    shared = _put_blob(snap, "shared-content")
    _put_blob(snap, "dead")

    # 两个会话都引用 shared。
    for sid in ("sess_a", "sess_b"):
        _write_jsonl(
            sessions / sid / "agent_file_index.jsonl",
            [{"path": "/f", "content_hash": shared}],
        )

    result = garbage_collect(
        sessions_root=sessions,
        snapshot_root_path=snap,
        enabled=True,
        dry_run=False,
        max_bytes=1,  # 强制超预算，触发删除
    )
    # shared 被引用 → 不可达集合不含 shared → 不删；dead 未引用 → 可删。
    assert (snap / shared).is_file(), "跨会话共享 blob 被误删"
    assert not (snap / "dead").exists(), "不可达 blob 应被回收"
    assert result.deleted == 1


def test_dry_run_and_disabled_never_delete(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snap = tmp_path / "snapshots"
    a = _put_blob(snap, "a")
    b = _put_blob(snap, "b")

    # disabled → 不删
    r1 = garbage_collect(
        sessions_root=sessions,
        snapshot_root_path=snap,
        enabled=False,
        dry_run=False,
        max_bytes=1,
    )
    assert (snap / a).is_file() and (snap / b).is_file()

    # enabled but dry_run → 不删
    r2 = garbage_collect(
        sessions_root=sessions,
        snapshot_root_path=snap,
        enabled=True,
        dry_run=True,
        max_bytes=1,
    )
    assert (snap / a).is_file() and (snap / b).is_file()
    assert r2.deleted == 0 and r2.deletable >= 1


def test_no_gc_within_budget(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snap = tmp_path / "snapshots"
    a = _put_blob(snap, "a")
    b = _put_blob(snap, "b")

    # 预算很大（未超）→ 即便启用也不删不可达 blob。
    result = garbage_collect(
        sessions_root=sessions,
        snapshot_root_path=snap,
        enabled=True,
        dry_run=False,
        max_bytes=10**12,
    )
    assert (snap / a).is_file() and (snap / b).is_file()
    assert result.deleted == 0


def test_list_snapshot_blobs_filters_junk(tmp_path: Path):
    snap = tmp_path / "snapshots"
    good = _put_blob(snap, "good")
    (snap / "not-a-hash.tmp").write_text("junk")
    entries = list_snapshot_blobs(snap)
    hashes = {item.hash for item in entries}
    assert good in hashes
    assert all(len(h) == 64 for h in hashes)


def test_snapshot_root_default(monkeypatch):
    # 无 XEYO_SNAPSHOTS_DIR 时回落到 ~/.xeyo/snapshots。
    # （conftest 全局把 XEYO_SNAPSHOTS_DIR 钉进 tmp；本测试验证的是
    #   「env 缺席」分支，故显式删除后再断言。）
    monkeypatch.delenv("XEYO_SNAPSHOTS_DIR", raising=False)
    assert str(snapshot_root()).endswith(("snapshots",))


def test_retained_turn_ids_recent_n_plus_baseline_anchor(tmp_path: Path):
    sid = "sess_a"
    _write_jsonl(
        tmp_path / sid / "turns.jsonl",
        [
            {"turn_id": "t1", "user_message_id": "u1", "started_at": 1.0},
            {"turn_id": "t2", "user_message_id": "u2", "started_at": 2.0},
            {"turn_id": "t3", "user_message_id": "u3", "started_at": 3.0},
        ],
    )
    # 无锚点时 keep_recent=1 → t1(基线) + t3(最近)
    tids, mids = retained_turn_ids(tmp_path / sid, 1)
    assert tids == {"t1", "t3"} and mids == {"u1", "u3"}
    # 标 u2 为锚点后 → t2 也保留
    _write_jsonl(
        tmp_path / sid / "checkpoints.jsonl",
        [{"checkpoint_id": "cp2", "user_message_id": "u2", "ts": 2.0, "anchor": True}],
    )
    tids2, mids2 = retained_turn_ids(tmp_path / sid, 1)
    assert "t2" in tids2 and "u2" in mids2


def test_turn_level_prune_old_turn_blobs(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snap = tmp_path / "snapshots"
    op1 = _put_blob(snap, "op-t1")
    op2 = _put_blob(snap, "op-t2")
    op3 = _put_blob(snap, "op-t3")
    cp2 = _put_blob(snap, "cp-t2")
    sid = "sess_a"
    _write_jsonl(
        sessions / sid / "turns.jsonl",
        [
            {"turn_id": "t1", "user_message_id": "u1", "started_at": 1.0},
            {"turn_id": "t2", "user_message_id": "u2", "started_at": 2.0},
            {"turn_id": "t3", "user_message_id": "u3", "started_at": 3.0},
        ],
    )
    _write_jsonl(
        sessions / sid / "operations.jsonl",
        [
            {"operation_id": "o1", "turn_id": "t1", "before_hash": op1},
            {"operation_id": "o2", "turn_id": "t2", "before_hash": op2},
            {"operation_id": "o3", "turn_id": "t3", "before_hash": op3},
        ],
    )
    _write_jsonl(
        sessions / sid / "checkpoints.jsonl",
        [
            {"checkpoint_id": "cp2", "user_message_id": "u2", "ts": 2.0, "entries": [["/f", cp2]]},
        ],
    )
    # keep_recent=1 → t2 被剪；op2 与 cp2 的 blob 不可达；t1/t3 保留
    reach = collect_reachable_blobs(sessions, keep_recent=1)
    assert op2 not in reach
    assert cp2 not in reach
    assert op1 in reach and op3 in reach
    # 保守：不传 keep_recent 全部可达
    all_reachable = collect_reachable_blobs(sessions)
    assert op2 in all_reachable and cp2 in all_reachable


def test_mark_checkpoint_anchor_persists_anchor(tmp_path: Path):
    sid = "sess_a"
    cp = _put_blob(tmp_path / "snapshots", "cp-content")
    _write_jsonl(
        tmp_path / sid / "checkpoints.jsonl",
        [{"checkpoint_id": "cp1", "user_message_id": "u1", "ts": 1.0, "entries": [["/f", cp]]}],
    )
    cpid = mark_checkpoint_anchor(sid, "u1", sessions_dir=tmp_path)
    assert cpid == "cp1"
    # 锚点读侧可识别 → 打点后 True，取消后 False。
    assert get_checkpoint_anchor(sid, "u1", sessions_dir=tmp_path) is True
    mark_checkpoint_anchor(sid, "u1", anchor=False, sessions_dir=tmp_path)
    assert get_checkpoint_anchor(sid, "u1", sessions_dir=tmp_path) is False


def test_retained_checkpoint_ids_near_n_plus_baseline(tmp_path: Path):
    sid = "sess_a"
    cps = [
        {"checkpoint_id": "cp1", "ts": 1.0, "entries": []},
        {"checkpoint_id": "cp2", "ts": 2.0, "entries": []},
        {"checkpoint_id": "cp3", "ts": 3.0, "entries": []},
        {"checkpoint_id": "cp4", "ts": 4.0, "entries": []},
        {"checkpoint_id": "cp5", "ts": 5.0, "entries": []},
    ]
    _write_jsonl(tmp_path / sid / "checkpoints.jsonl", cps)
    # keep_recent=2 → 最近 cp5/cp4 + 基线 cp1。
    assert retained_checkpoint_ids(tmp_path / sid, 2) == {"cp1", "cp4", "cp5"}


def test_anchor_checkpoint_always_retained(tmp_path: Path):
    sid = "sess_a"
    cps = [
        {"checkpoint_id": "cp1", "ts": 1.0, "entries": []},
        {"checkpoint_id": "cp2", "ts": 2.0, "anchor": True, "entries": []},
        {"checkpoint_id": "cp3", "ts": 3.0, "entries": []},
    ]
    _write_jsonl(tmp_path / sid / "checkpoints.jsonl", cps)
    # keep_recent=1 → 最近 cp3 + 基线 cp1 + 锚点 cp2。
    assert retained_checkpoint_ids(tmp_path / sid, 1) == {"cp1", "cp2", "cp3"}


def test_keep_recent_prunes_old_checkpoint_blob(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snap = tmp_path / "snapshots"
    blob_base = _put_blob(snap, "baseline-only")
    blob_mid = _put_blob(snap, "mid-only")
    blob_recent = _put_blob(snap, "recent-only")
    sid = "sess_a"
    # cp1=基线、cp2=中间(将被剪)、cp3=最近。
    _write_jsonl(
        sessions / sid / "checkpoints.jsonl",
        [
            {"checkpoint_id": "cp1", "ts": 1.0, "entries": [["/f", blob_base]]},
            {"checkpoint_id": "cp2", "ts": 2.0, "entries": [["/f", blob_mid]]},
            {"checkpoint_id": "cp3", "ts": 3.0, "entries": [["/f", blob_recent]]},
        ],
    )
    # keep_recent=1 → 保留 cp1(基线)+cp3(最近)；cp2 专属 blob_mid 被剪。
    reachable = collect_reachable_blobs(sessions, keep_recent=1)
    assert blob_mid not in reachable
    assert blob_base in reachable
    assert blob_recent in reachable
    # 保守：不传 keep_recent 时全部可达。
    all_reachable = collect_reachable_blobs(sessions)
    assert blob_mid in all_reachable

