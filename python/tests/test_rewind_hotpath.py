"""回溯 v3 热路径回归（docs/实施计划/32 v3.1 修订）。

覆盖评审要求的核心用例：
- 发送冻结（freeze_checkpoint 幂等）+ turn 起止双向差量同步索引
- Continue：整轮截断 → orphan 先落盘 → transcript 原子重写 → 文件恢复 → Undo 回放
- Restore：transcript 不动；用户手改路径脏跳过；agent 新建路径删除
- 幂等键复用 / Undo 冲突保护（评审 #5）
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from rewind.hotpath import (
    RewindHotpath,
    RewindStateError,
    RewindValidationError,
)
from rewind.index import (
    AgentFileIndex,
    capture_turn_baseline,
    freeze_checkpoint,
    load_checkpoint,
    sync_index_from_turn_diff,
)
from rewind.snapshot import SnapshotStore
from session.persistence import safe_session_filename


def _write_transcript(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


@pytest.fixture()
def env(tmp_path: Path):
    sessions = tmp_path / "sessions"
    snapshots = tmp_path / "snapshots"
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    sid = "s:hotpath"
    store = SnapshotStore(sid, root=snapshots, enabled=True)
    transcript = sessions / "s__hotpath.jsonl"
    _write_transcript(
        transcript,
        [
            {"id": "m1", "role": "user", "text": "q1"},
            {"id": "m2", "role": "assistant", "text": "a1"},
            {"id": "m3", "role": "user", "text": "q2"},
            {"id": "m4", "role": "assistant", "text": "a2"},
        ],
    )
    return {
        "sessions": sessions,
        "snapshots": store,
        "workspace": workspace,
        "sid": sid,
        "transcript": transcript,
    }


def _wait_status(hot: RewindHotpath, rewind_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        event = hot.get_event(rewind_id)
        assert event is not None
        if event.get("status") in {"committed", "partial", "failed"}:
            return event
        time.sleep(0.02)
    raise AssertionError("restore did not settle in time")


def test_freeze_checkpoint_is_idempotent_and_loads(env):
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    data = (ws / "a.txt").read_bytes()
    stat = (ws / "a.txt").lstat()
    index.upsert(
        "a.txt",
        content_hash=env["snapshots"].put_bytes(data).content_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    cp1 = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    cp2 = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    assert cp1.checkpoint_id == cp2.checkpoint_id
    assert cp1.entries == {"a.txt": cp1.entries["a.txt"]}
    loaded = load_checkpoint(env["sid"], cp1.checkpoint_id, sessions_dir=env["sessions"])
    assert loaded is not None and loaded.entries == cp1.entries


def test_turn_diff_sync_records_before_and_after(env):
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    stat = (ws / "a.txt").lstat()
    hash_v1 = env["snapshots"].put_bytes(b"v1").content_hash
    index.upsert(
        "a.txt",
        content_hash=hash_v1,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    # turn 开始基线（v1 时刻）
    baseline = capture_turn_baseline(ws)
    # agent turn 内：改 a.txt、新建 new.txt
    time.sleep(0.01)
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    (ws / "new.txt").write_text("n", encoding="utf-8")
    report = sync_index_from_turn_diff(
        env["sid"],
        baseline,
        snapshots=env["snapshots"],
        sessions_dir=env["sessions"],
    )
    assert report["upserted"] == 2
    entries = index.entries()
    assert entries["a.txt"].content_hash == env["snapshots"].put_bytes(b"v2").content_hash
    assert entries["new.txt"].content_hash is not None
    # new.txt 是 turn 中首触 → before 缺失（评审 #1 的兜底边界）
    assert "new.txt" in report["before_missing"]


def test_continue_roundtrip_truncate_restore_undo(env):
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    stat = (ws / "a.txt").lstat()
    index.upsert(
        "a.txt",
        content_hash=env["snapshots"].put_bytes(b"v1").content_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    cp = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    # agent turn：改 a.txt 为 v2、新建 new.txt，并同步进索引（模拟 turn 结束差量）
    baseline = capture_turn_baseline(ws)
    time.sleep(0.01)
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    (ws / "new.txt").write_text("n", encoding="utf-8")
    sync_index_from_turn_diff(
        env["sid"], baseline, snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )

    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="continue",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        edited_text="换个问法重来",
        idempotency_key="key-1",
        confirmed=True,
    )
    assert result.transcript_committed is True
    assert result.removed_rows == 2

    # 46 号 replace 事件化：不落 orphan、不重写 transcript——原始行保留 + marker 追加。
    orphan_path = hot.orphans_dir / f"{result.rewind_id}.jsonl"
    assert not orphan_path.is_file()
    raw_rows = [json.loads(l) for l in env["transcript"].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [row.get("id") for row in raw_rows if row.get("id")] == ["m1", "m2", "m3", "m4"]
    from session.surface import is_surface_marker

    assert sum(1 for row in raw_rows if is_surface_marker(row)) == 1
    # 模型可见面（hydrate 同源 fold）= 保留前缀。
    from session.hydrate import messages_from_transcript

    visible = messages_from_transcript(env["transcript"])
    assert [m.id for m in visible] == ["m1", "m2"]

    event = _wait_status(hot, result.rewind_id)
    assert event["status"] == "committed", event
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v1"
    assert not (ws / "new.txt").exists()

    # Undo：追加 undo marker（对话恢复）+ 文件回放（评审 #5：无新消息时才允许）
    undo = hot.undo(result.rewind_id, confirmed=True)
    assert undo["conversation"]["restored"] == 2
    assert undo["files"]["restored"] >= 1
    assert undo["files"]["skipped_dirty"] == []
    visible_after = messages_from_transcript(env["transcript"])
    assert [m.id for m in visible_after] == ["m1", "m2", "m3", "m4"]
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v2"
    assert (ws / "new.txt").read_text(encoding="utf-8") == "n"

    # 幂等：undone 是「键已释放」的陈旧终态——同 key 重试必须发起新回溯，
    # 而不是重放已撤销的旧事件（GUI pollSettled 不认 undone，只会白等超时）。
    again = hot.rewind(
        mode="continue",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        edited_text="换个问法重来",
        idempotency_key="key-1",
        confirmed=True,
    )
    assert again.reused is False
    assert again.rewind_id != result.rewind_id


def test_restore_mode_keeps_transcript_and_skips_dirty(env):
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    stat = (ws / "a.txt").lstat()
    index.upsert(
        "a.txt",
        content_hash=env["snapshots"].put_bytes(b"v1").content_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    cp = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    # agent 改成 v2 并入索引，随后用户手改成 v-user（签名与索引不符 → 脏）
    time.sleep(0.01)
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    baseline = capture_turn_baseline(ws)
    sync_index_from_turn_diff(
        env["sid"], baseline, snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    time.sleep(0.01)
    (ws / "a.txt").write_text("v-user", encoding="utf-8")

    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="restore",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        confirmed=True,
    )
    assert result.transcript_committed is False
    event = _wait_status(hot, result.rewind_id)
    assert event["status"] == "partial", event
    assert event["restore"]["skipped_dirty"] == ["a.txt"]
    # 用户手改内容不被覆盖（合同：脏路径跳过）
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v-user"
    # transcript 一行不动
    rows = [json.loads(l) for l in env["transcript"].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [row["id"] for row in rows] == ["m1", "m2", "m3", "m4"]


def test_undo_blocked_when_new_messages_appended(env):
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    stat = (ws / "a.txt").lstat()
    index.upsert(
        "a.txt",
        content_hash=env["snapshots"].put_bytes(b"v1").content_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    cp = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="continue",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        edited_text="again",
        confirmed=True,
    )
    _wait_status(hot, result.rewind_id)
    # rewind 之后新 turn 落盘
    with open(env["transcript"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "m5", "role": "user", "text": "new turn"}) + "\n")
    with pytest.raises(RewindStateError):
        hot.undo(result.rewind_id, confirmed=True)


def test_validation_errors(env):
    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=env["workspace"],
    )
    with pytest.raises(RewindValidationError):
        hot.rewind(mode="continue", target_message_id="m3", confirmed=True)
    with pytest.raises(RewindValidationError):
        hot.rewind(mode="continue", target_message_id="m3", edited_text="x", confirmed=False)
    with pytest.raises(RewindValidationError):
        hot.rewind(mode="branch", target_message_id="m3", edited_text="x", confirmed=True)


def _append_journal_operation(sessions: Path, sid: str, *, path: str, before_hash: str | None) -> None:
    """直接 append 一条 operations.jsonl 记录，模拟工具层 mutation 的 journal 写回。

    聚焦删除分支对「既有文件被 agent 首次修改」与「agent 新建文件」的区分：
    前者 before_hash 非空（inverse_kind='restore_snapshot'），后者 before_hash 为 None。
    """
    ops = sessions / safe_session_filename(sid) / "operations.jsonl"
    ops.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "session_id": sid,
        "operation_id": f"op_{path.replace('/', '_')}",
        "turn_id": "turn_x",
        "status": "completed",
        "path": path,
        "before_hash": before_hash,
        "after_hash": "after-hash-placeholder",
        "inverse_kind": "restore_snapshot" if before_hash else "delete_file",
        "inverse_payload": {
            "file_existed_before": before_hash is not None,
            "before_content_hash": before_hash,
        },
    }
    with open(ops, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_restore_recovers_first_touch_existing_file_not_deletes(env):
    """BUG-1 回归：既有用户文件本轮被 agent 首次修改（此前从未入索引）。

    checkpoint 冻结时该文件不在 cp.entries；turn 后 agent 首次修改它，它进入
    index.entries。回滚到 checkpoint 时删除分支会把它当作「agent 新建」而删除。
    正确行为：journal 记录 before_hash（existed_before=True）→ 恢复 before 内容，
    绝不删除（I7 用户数据安全）。
    """
    ws = env["workspace"]
    # 既有用户文件：在 checkpoint 冻结前存在，但从未被 agent 索引。
    (ws / "user.txt").write_text("user-original", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    cp = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    # 本轮 agent 首次修改该既有文件 → 入索引 + journal 记 before_hash。
    time.sleep(0.01)
    baseline = capture_turn_baseline(ws)  # 修改前基线
    (ws / "user.txt").write_text("agent-mutated", encoding="utf-8")
    sync_index_from_turn_diff(
        env["sid"], baseline, snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    abs_user = str((ws / "user.txt").resolve()).replace("\\", "/")
    before_hash = env["snapshots"].put_bytes(b"user-original").content_hash
    _append_journal_operation(
        env["sessions"], env["sid"], path=abs_user, before_hash=before_hash
    )

    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="restore",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        confirmed=True,
    )
    event = _wait_status(hot, result.rewind_id)
    assert event["status"] in {"committed", "partial"}, event
    # 关键：既有文件被恢复原文，而不是被删除。
    assert (ws / "user.txt").exists()
    assert (ws / "user.txt").read_text(encoding="utf-8") == "user-original"
    assert "user.txt" not in event["restore"]["deleted"]
    assert "user.txt" in event["restore"]["restored"]


def test_continue_no_checkpoint_is_partial_not_committed(env):
    """BUG-2 回归：continue 模式下无检查点 → 不应假置 committed。

    对话确实截断，但**没有文件检查点**可恢复。若置 committed，前端会把「文件在
    后台恢复中/已恢复」的误导文案给用户。正确行为：置 partial + no_checkpoint 标记，
    让前端明确提示「仅截断对话，文件未回滚」。
    """
    ws = env["workspace"]
    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="continue",
        target_message_id="m3",
        checkpoint_id=None,  # 明确无检查点
        edited_text="重新问一遍",
        confirmed=True,
    )
    assert result.transcript_committed is True
    event = _wait_status(hot, result.rewind_id)
    assert event["status"] == "partial", event
    assert event["restore"] is not None
    assert event["restore"].get("no_checkpoint") is True
    # 对话确实截断了（fold 可见面 = 保留前缀；原始行 + marker 保留在文件里）
    from session.hydrate import messages_from_transcript

    visible = messages_from_transcript(env["transcript"])
    assert [m.id for m in visible] == ["m1", "m2"]


def test_restore_one_file_managed_uses_content_hash_not_signature(env):
    """BUG-3 回归：managed 判定用内容哈希而非 (size, mtime) 签名。

    索引同步失败 / 文件在 turn 后再次被触碰造成的签名漂移，不应把合法 agent 改动
    误判为「用户手改」而跳过恢复。
    """
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    stat = (ws / "a.txt").lstat()
    index.upsert(
        "a.txt",
        content_hash=env["snapshots"].put_bytes(b"v1").content_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    cp = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    # agent 改成 v2 并入索引（索引记录 v2 的 size/mtime）
    time.sleep(0.01)
    baseline = capture_turn_baseline(ws)  # 修改前基线
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    sync_index_from_turn_diff(
        env["sid"], baseline, snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    # 模拟「文件在 turn 后被触碰」：改 mtime，但内容仍是 agent 写的 v2（签名漂移）
    time.sleep(0.03)
    (ws / "a.txt").write_text("v2", encoding="utf-8")

    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="restore",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        confirmed=True,
    )
    event = _wait_status(hot, result.rewind_id)
    # 内容哈希与索引 entry.content_hash（=v2）一致 → 视为 managed → 恢复，不算脏跳过。
    assert event["status"] in {"committed", "partial"}, event
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v1"
    assert "a.txt" not in event["restore"]["skipped_dirty"]


def test_undo_resumes_after_partial_conversation_replay(env):
    """P0 回归：undo 半途失败（对话已回放、文件未回放）后重试必须续跑，
    而不是命中「orphan ids already present」409 永久卡死 + transcript 重复。"""
    ws = env["workspace"]
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    index = AgentFileIndex(env["sid"], sessions_dir=env["sessions"])
    stat = (ws / "a.txt").lstat()
    index.upsert(
        "a.txt",
        content_hash=env["snapshots"].put_bytes(b"v1").content_hash,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source="turn_diff",
    )
    cp = freeze_checkpoint(
        env["sid"], "m3", snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )
    baseline = capture_turn_baseline(ws)
    time.sleep(0.01)
    (ws / "a.txt").write_text("v2", encoding="utf-8")
    (ws / "new.txt").write_text("n", encoding="utf-8")
    sync_index_from_turn_diff(
        env["sid"], baseline, snapshots=env["snapshots"], sessions_dir=env["sessions"]
    )

    hot = RewindHotpath(
        env["sid"],
        sessions_dir=env["sessions"],
        snapshots=env["snapshots"],
        workspace_root=ws,
    )
    result = hot.rewind(
        mode="continue",
        target_message_id="m3",
        checkpoint_id=cp.checkpoint_id,
        edited_text="again",
        idempotency_key="key-undo",
        confirmed=True,
    )
    event = _wait_status(hot, result.rewind_id)
    assert event["status"] == "committed", event

    # 46 号 marker 语义：模拟「undo marker 已追加、文件部分失败」的续跑——
    # conversation 部分幂等跳过，只重做文件；对话恢复且无重复行。
    from rewind.hotpath import _append_transcript
    from session.surface import rewind_undo_marker_row

    _append_transcript(
        env["transcript"], [rewind_undo_marker_row(result.rewind_id)]
    )

    undo = hot.undo(result.rewind_id, confirmed=True)
    assert undo["conversation"]["resumed"] is True
    assert undo["conversation"]["restored"] == 0
    assert undo["files"]["restored"] >= 1
    # fold 后对话完整（原始行 + 两个 marker 都在文件里，fold 恢复可见面）。
    from session.hydrate import messages_from_transcript

    visible = messages_from_transcript(env["transcript"])
    assert [m.id for m in visible] == ["m1", "m2", "m3", "m4"]
    assert (ws / "a.txt").read_text(encoding="utf-8") == "v2"
    assert (ws / "new.txt").read_text(encoding="utf-8") == "n"


def test_normalize_rel_path_preserves_root_dotfiles():
    """lstrip("./") 按字符集剥离，曾把 ".gitignore"/".env" 改写成 "gitignore"/"env"，
    restore/undo 落到错误路径。"""
    from rewind.index import _normalize_rel_path

    assert _normalize_rel_path(".gitignore") == ".gitignore"
    assert _normalize_rel_path(".env") == ".env"
    assert _normalize_rel_path("./a/b.txt") == "a/b.txt"
    assert _normalize_rel_path(".//a") == "a"
    assert _normalize_rel_path("/x/y") == "x/y"
    assert _normalize_rel_path("a\\b.txt") == "a/b.txt"
    assert _normalize_rel_path("") == ""
