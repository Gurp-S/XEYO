"""session/surface fold 语义 + 46 号启动对账 + legacy orphan undo 兼容。"""

from __future__ import annotations

import json
from pathlib import Path


from rewind.hotpath import mark_crashed_rewinds
from session.hydrate import messages_from_transcript
from session.surface import (
    active_markers,
    fold_surface_rows,
    has_undo_marker,
    rewind_marker_row,
    rewind_undo_marker_row,
)


def _rows(*ids: str) -> list[dict]:
    return [
        {"id": i, "role": "user" if idx % 2 == 0 else "assistant", "content": f"c-{i}"}
        for idx, i in enumerate(ids)
    ]


def test_fold_identity_without_markers():
    rows = _rows("m1", "m2", "m3")
    assert [r["id"] for r in fold_surface_rows(rows)] == ["m1", "m2", "m3"]


def test_fold_shadows_from_target_inclusive():
    rows = _rows("m1", "m2", "m3", "m4")
    rows.append(rewind_marker_row("rw1", "m3"))
    assert [r["id"] for r in fold_surface_rows(rows)] == ["m1", "m2"]


def test_fold_two_rewinds_compose():
    rows = _rows("m1", "m2", "m3", "m4", "m5")
    rows.append(rewind_marker_row("rw1", "m4"))  # 可见面: m1..m3
    rows.append(rewind_marker_row("rw2", "m2"))  # 可见面: m1
    assert [r["id"] for r in fold_surface_rows(rows)] == ["m1"]


def test_fold_undo_restores_and_is_idempotent():
    rows = _rows("m1", "m2", "m3", "m4")
    rows.append(rewind_marker_row("rw1", "m3"))
    rows.append(rewind_undo_marker_row("rw1"))
    rows.append(rewind_undo_marker_row("rw1"))  # 重复 undo 幂等
    assert [r["id"] for r in fold_surface_rows(rows)] == ["m1", "m2", "m3", "m4"]
    assert active_markers(rows) == []
    assert has_undo_marker(rows, "rw1") is True


def test_fold_missing_shadow_from_is_conservative():
    """marker 的影子首行不在可见面（如 v2 物理重写掉）→ 不隐藏任何行。"""
    rows = _rows("m1", "m2")
    rows.append(rewind_marker_row("rw1", "gone"))
    assert [r["id"] for r in fold_surface_rows(rows)] == ["m1", "m2"]


def test_fold_keeps_non_message_rows():
    rows = _rows("m1", "m2")
    rows.append({"role": "ui_thought", "id": "t1", "content": "thinking"})
    rows.append(rewind_marker_row("rw1", "m2"))
    folded = fold_surface_rows(rows)
    # m2 被影子化；无 role 的未知行/marker 不出现在消息面；ui_thought 有 id
    # 但同样在影子区间之后被影子化。
    assert [r["id"] for r in folded if "role" in r] == ["m1"]


def test_hydrate_messages_from_transcript_folds(tmp_path: Path):
    path = tmp_path / "s__fold.jsonl"
    payload = _rows("m1", "m2", "m3") + [rewind_marker_row("rw1", "m3")]
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in payload),
        encoding="utf-8",
    )
    msgs = messages_from_transcript(path)
    assert [m.id for m in msgs] == ["m1", "m2"]


def test_mark_crashed_rewinds_synthesizes_event_for_orphan_marker(
    tmp_path: Path, monkeypatch
):
    """marker 已落盘、事件未落盘的崩溃窗口：启动对账补合成事件（幂等）。"""
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    sid = "s:orphmarker"
    safe = "s__orphmarker"
    sdir = tmp_path / safe
    sdir.mkdir(parents=True)
    transcript = tmp_path / f"{safe}.jsonl"
    payload = _rows("m1", "m2", "m3") + [rewind_marker_row("rw_crash", "m2")]
    transcript.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in payload),
        encoding="utf-8",
    )

    n1 = mark_crashed_rewinds(tmp_path)
    assert n1 == 1
    events = [json.loads(l) for l in (sdir / "rewind_events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert events[0]["rewind_id"] == "rw_crash"
    # 终态 partial + no_checkpoint（仅截断对话；且不在 in-flight 集合，保证幂等）。
    assert events[0]["status"] == "partial"
    assert events[0]["surface_marker"] is True
    assert events[0]["restore"]["no_checkpoint"] is True
    assert events[0]["after_message_id"] == "m1"

    # 幂等：第二次扫描不再重复。
    assert mark_crashed_rewinds(tmp_path) == 0


def test_legacy_orphan_event_undo_still_works(tmp_path: Path):
    """46 号之前的事件（orphan 物理回放路径）undo 不得被 marker 化改造破坏。"""
    from rewind.hotpath import RewindHotpath
    from rewind.snapshot import SnapshotStore

    sid = "s:legacy"
    safe = "s__legacy"
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    snapshots = SnapshotStore(sid, root=tmp_path / "snapshots", enabled=True)
    transcript = sessions / f"{safe}.jsonl" if False else tmp_path / "sessions.jsonl"
    transcript = sessions / f"{safe}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    rows = _rows("m1", "m2", "m3", "m4")
    transcript.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    # 手工构造 legacy 事件 + orphan 文件（旧版本 rewind 的产物）。
    orphans = sessions / safe / "orphans"
    orphans.mkdir(parents=True)
    orphan_rows = rows[2:]
    (orphans / "rw_old.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in orphan_rows),
        encoding="utf-8",
    )
    event = {
        "rewind_id": "rw_old",
        "session_id": sid,
        "mode": "continue",
        "ts": 0.0,
        "target_message_id": "m3",
        "checkpoint_id": "",
        "surface_marker": False,
        "orphan_id": "rw_old",
        "orphan_count": 2,
        "retained_row_count": 2,
        "after_message_id": "m2",
        "idempotency_key": "",
        "pill_summary": {"edited_digest": "", "removed_rows": 2},
        "status": "committed",
        "restore": None,
        "pre_rewind_index": [],
        "undone": False,
        "error": None,
    }
    events_path = sessions / safe / "rewind_events.jsonl"
    events_path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # 旧 rewind 已物理截断 transcript 到前缀。
    transcript.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[:2]),
        encoding="utf-8",
    )

    hot = RewindHotpath(
        sid, sessions_dir=sessions, snapshots=snapshots, workspace_root=tmp_path
    )
    undo = hot.undo("rw_old", confirmed=True)
    assert undo["conversation"]["restored"] == 2
    assert undo["conversation"].get("resumed") in (None, False)
    msgs = messages_from_transcript(transcript)
    assert [m.id for m in msgs] == ["m1", "m2", "m3", "m4"]
