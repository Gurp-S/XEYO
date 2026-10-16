"""UI acknowledgements must survive writer failure and overlapping retries."""
import asyncio
import importlib
import threading

import pytest

writer = importlib.import_module("session.record_transcript")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    assert writer.flush_pending_sync()
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_NO_SESSION_PERSISTENCE", raising=False)
    yield tmp_path
    assert writer.flush_pending_sync()


@pytest.mark.asyncio
async def test_ack_waits_for_disk_without_blocking_event_loop(isolated, monkeypatch):
    from server.thought_persistence import persist_thoughts
    entered, release = threading.Event(), threading.Event()
    original = writer._write_batch
    def blocked(batch):
        entered.set()
        assert release.wait(5)
        original(batch)
    with monkeypatch.context() as patch:
        patch.setattr(writer, "_write_batch", blocked)
        task = asyncio.create_task(persist_thoughts([{"id": "one", "text": "reason"}], session_id="slow", known_ids=set()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await asyncio.sleep(0.02)
            assert not task.done()
            assert not (isolated / "slow.jsonl").exists()
        finally:
            release.set()
        assert await task == 1
    assert len(writer.load_transcript(isolated / "slow.jsonl")) == 1


@pytest.mark.asyncio
async def test_route_failure_then_same_id_retry_is_durable_and_unique(isolated, monkeypatch):
    from fastapi import HTTPException
    from server.routers.sessions import sync_ui_thoughts, UiThoughtsSyncRequest
    body = UiThoughtsSyncRequest(thoughts=[{"id": "retry-one", "text": "reason"}])
    original = writer._write_batch
    def partially_written(batch):
        original(batch)
        raise OSError("injected failure after write")
    with monkeypatch.context() as patch:
        patch.setattr(writer, "_write_batch", partially_written)
        with pytest.raises(HTTPException) as exc:
            await sync_ui_thoughts("retry-durable", body)
        assert exc.value.status_code == 503
    result = await sync_ui_thoughts("retry-durable", body)
    assert result == {"ok": True, "written": 0}
    rows = writer.load_transcript(isolated / "retry-durable.jsonl")
    assert [row["id"] for row in rows] == ["retry-one"]


@pytest.mark.asyncio
async def test_other_session_failure_does_not_poison_ack(isolated, monkeypatch):
    from server.thought_persistence import persist_thoughts
    original = writer._write_batch
    def broken_path(batch):
        if batch[0][1].endswith("broken.jsonl"):
            raise OSError("unavailable path")
        original(batch)
    with monkeypatch.context() as patch:
        patch.setattr(writer, "_write_batch", broken_path)
        with pytest.raises(OSError):
            await persist_thoughts([{"id": "bad", "text": "reason"}], session_id="broken", known_ids=set())
        assert await persist_thoughts([{"id": "good", "text": "reason"}], session_id="working", known_ids=set()) == 1
        assert writer.load_transcript(isolated / "working.jsonl")[0]["id"] == "good"


@pytest.mark.asyncio
async def test_disabled_persistence_does_not_ack(isolated, monkeypatch):
    from server.thought_persistence import persist_thoughts
    monkeypatch.setenv("XEYO_NO_SESSION_PERSISTENCE", "1")
    with pytest.raises(OSError, match="disabled"):
        await persist_thoughts([{"id": "one", "text": "reason"}], session_id="disabled", known_ids=set())
    assert not (isolated / "disabled.jsonl").exists()
