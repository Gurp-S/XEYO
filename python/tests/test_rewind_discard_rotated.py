"""rollback must discard rotated transcript archives so hydrate cannot resurrect turns."""

from __future__ import annotations

from pathlib import Path

from session.record_transcript import (
    discard_rotated_transcripts,
    rotated_transcript_path,
)


def test_discard_rotated_transcripts_removes_old_archives(tmp_path: Path) -> None:
    current = tmp_path / "sess.jsonl"
    current.write_text('{"id":"a"}\n', encoding="utf-8")
    old1 = rotated_transcript_path(current)
    old1.write_text('{"id":"zombie"}\n', encoding="utf-8")
    old2 = current.with_name(current.name + ".old2")
    old2.write_text('{"id":"older"}\n', encoding="utf-8")

    removed = discard_rotated_transcripts(current)
    assert str(old1) in removed
    assert str(old2) in removed
    assert not old1.exists()
    assert not old2.exists()
    assert current.read_text(encoding="utf-8") == '{"id":"a"}\n'
