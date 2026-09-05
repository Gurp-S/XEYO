from __future__ import annotations

import pytest

from engine.query_engine import build_default_engine
from msgtypes.events import FinalEvent


@pytest.mark.asyncio
async def test_query_engine_commits_turn_and_revision_when_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))

    engine = build_default_engine(model_backend="fake")
    events = [event async for event in engine.submit("hello")]

    assert any(isinstance(event, FinalEvent) for event in events)
    turns = engine._rewind_journal.list_turns()  # noqa: SLF001 - integration seam
    assert len(turns) == 1
    assert turns[0].status == "committed"
    assert turns[0].user_message_id
    revisions = engine._revision_store.list()  # noqa: SLF001 - integration seam
    assert len(revisions) == 1
    assert revisions[0].head_turn_id == turns[0].turn_id
    assert any(event.event_type == "turn_committed" for event in engine._rewind_journal.list_audit())


@pytest.mark.asyncio
async def test_query_engine_keeps_rewind_disabled_when_opted_out(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XEYO_REWIND_ENABLED", "0")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))

    engine = build_default_engine(model_backend="fake")
    events = [event async for event in engine.submit("hello")]

    assert any(isinstance(event, FinalEvent) for event in events)
    assert engine._rewind_journal.list_turns() == []  # noqa: SLF001
    assert engine._revision_store.list() == []  # noqa: SLF001
