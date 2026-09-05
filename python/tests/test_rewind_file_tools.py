from __future__ import annotations

import asyncio
import json

from engine.abort import AbortController
from rewind.context import RewindExecutionContext, bind_context
from rewind.journal import OperationJournal
from rewind.snapshot import SnapshotStore
from tools.file_write_tool.file_write_tool import FileWriteTool


def test_file_write_records_content_addressed_inverse_metadata(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sessions = tmp_path / "sessions"
    snapshots = tmp_path / "snapshots"
    journal = OperationJournal("session-1", sessions_dir=sessions, enabled=True)
    snapshot_store = SnapshotStore("session-1", root=snapshots, enabled=True)
    context = RewindExecutionContext(
        session_id="session-1",
        turn_id="turn-1",
        revision_id="rev-1",
        journal=journal,
        snapshots=snapshot_store,
    )

    target = workspace / "sample.txt"
    tool = FileWriteTool(cwd=str(workspace))
    with bind_context(context):
        result = asyncio.run(
            tool.execute(
                {"file_path": str(target), "content": "hello\nworld\n"},
                AbortController(),
            )
        )

    assert not result.is_error
    operations = journal.list_operations(turn_id="turn-1")
    assert len(operations) == 1
    operation = operations[0]
    assert operation.status == "completed"
    assert operation.inverse_kind == "delete_file"
    assert operation.before_hash is None
    assert operation.after_hash is not None
    assert "old_content" not in operation.to_dict()
    assert "new_content" not in operation.to_dict()
    assert snapshot_store.get_text(operation.after_hash) == "hello\nworld\n"

    raw = json.loads((sessions / "session-1" / "operations.jsonl").read_text(encoding="utf-8").splitlines()[1])
    raw_text = json.dumps(raw, ensure_ascii=False)
    assert "hello\\nworld\\n" not in raw_text


def test_file_edit_records_before_and_after_snapshots(tmp_path) -> None:
    from tools.file_edit_tool.file_edit_tool import FileEditTool
    from tools.fileio.read_state import FileStateEntry, ReadFileState
    from tools.fileio.text import get_mtime_ms

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "sample.txt"
    target.write_text("before\n", encoding="utf-8")
    state = ReadFileState()
    state.set(
        str(target),
        FileStateEntry(content="before\n", timestamp=get_mtime_ms(str(target))),
    )
    journal = OperationJournal(
        "session-2", sessions_dir=tmp_path / "sessions", enabled=True
    )
    snapshot_store = SnapshotStore(
        "session-2", root=tmp_path / "snapshots", enabled=True
    )
    context = RewindExecutionContext(
        session_id="session-2",
        turn_id="turn-2",
        revision_id="rev-2",
        journal=journal,
        snapshots=snapshot_store,
    )
    tool = FileEditTool(cwd=str(workspace), read_state=state)

    with bind_context(context):
        result = asyncio.run(
            tool.execute(
                {
                    "file_path": str(target),
                    "old_string": "before",
                    "new_string": "after",
                },
                AbortController(),
            )
        )

    assert not result.is_error
    operation = journal.list_operations(turn_id="turn-2")[0]
    assert operation.inverse_kind == "restore_snapshot"
    assert operation.before_hash and operation.after_hash
    assert snapshot_store.get_text(operation.before_hash) == "before\n"
    assert snapshot_store.get_text(operation.after_hash) == "after\n"
    assert result.metadata == {"operation_id": operation.operation_id}
