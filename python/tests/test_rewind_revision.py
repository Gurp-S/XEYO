from __future__ import annotations

import pytest

from rewind.revision import RevisionStore


def test_revision_store_commits_turns_and_creates_truncate_branch(tmp_path) -> None:
    store = RevisionStore("session-1", sessions_dir=tmp_path, enabled=True)
    first = store.commit_turn("turn-1", message_ids=("msg-1", "msg-2"))
    assert first is not None
    second = store.commit_turn("turn-2", message_ids=("msg-3",))
    assert second is not None
    assert store.head().revision_id == second.revision_id
    assert store.head().turn_ids == ("turn-1", "turn-2")

    branch = store.truncate_to(first.revision_id, metadata={"reason": "edit_history"})
    assert branch.parent_revision_id == first.revision_id
    assert branch.turn_ids == ("turn-1",)
    assert branch.message_ids == ("msg-1", "msg-2")
    assert store.head().revision_id == branch.revision_id
    assert len(store.list(latest_only=True)) == 3
    assert len(store.list(latest_only=False)) == 3


def test_revision_store_requires_existing_target(tmp_path) -> None:
    store = RevisionStore("session-2", sessions_dir=tmp_path, enabled=True)
    with pytest.raises(KeyError, match="revision not found"):
        store.truncate_to("rev_missing")


def test_revision_store_disabled_does_not_create_files(tmp_path) -> None:
    store = RevisionStore("session-3", sessions_dir=tmp_path, enabled=False)
    assert store.commit_turn("turn-1") is None
    assert store.list() == []
    assert not (tmp_path / "session-3").exists()
