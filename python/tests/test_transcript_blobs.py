from __future__ import annotations

import json
from pathlib import Path

from msgtypes.message import Message
from session.record_transcript import (
	load_transcript,
	record_transcript_sync,
)
from session.transcript_blobs import (
	blob_file,
	resolve_transcript_row,
	row_from_message,
)


def test_row_externalizes_large_content(tmp_path: Path, monkeypatch):
	monkeypatch.setenv("XEYO_TRANSCRIPT_BLOB_THRESHOLD", "512")
	anchor = tmp_path / "sess.jsonl"
	big = "x" * 600
	msg = Message(id="big-1", role="tool", content=big, name="Read")
	row = row_from_message(msg, anchor=anchor)
	assert "content_ref" in row
	assert "content" not in row
	assert blob_file(anchor, "big-1").is_file()
	restored = resolve_transcript_row(row, anchor)
	assert restored["content"] == big


def test_record_transcript_sync_roundtrip_blob(tmp_path: Path, monkeypatch):
	monkeypatch.setenv("XEYO_TRANSCRIPT_BLOB_THRESHOLD", "512")
	path = tmp_path / "s.jsonl"
	big = "y" * 600
	msg = Message(id="t-large", role="tool", content=big, name="Grep")
	known: set[str] = set()
	n = record_transcript_sync([msg], session_id="s", path=path, known_ids=known)
	assert n == 1
	rows = load_transcript(path)
	assert len(rows) == 1
	assert rows[0].get("content_ref")
	line = json.dumps(rows[0])
	assert len(line.encode("utf-8")) < len(big)


def test_small_content_stays_inline(tmp_path: Path):
	anchor = tmp_path / "s.jsonl"
	msg = Message(id="small", role="assistant", content="hi")
	row = row_from_message(msg, anchor=anchor)
	assert row.get("content") == "hi"
	assert "content_ref" not in row
