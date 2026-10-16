"""P2-9: transcript 轮转（超限归档）+ 跨归档读取。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msgtypes.message import user_message
from session.hydrate import messages_from_transcript
from session.record_transcript import (
	_load_written_ids,
	record_transcript_sync,
	rotated_transcript_path,
	rotated_transcript_paths,
	transcript_read_paths,
)


def test_rotation_creates_archive_and_keeps_continuity(tmp_path, monkeypatch):
	"""单次轮转场景：old1 + 当前文件可完整恢复全部历史。"""
	monkeypatch.setenv("XEYO_TRANSCRIPT_MAX_BYTES", "1500")
	p = tmp_path / "s.jsonl"
	msgs = [user_message(f"m{i} " + "x" * 80) for i in range(12)]
	known: set[str] = set()
	for m in msgs:
		record_transcript_sync([m], session_id="s", path=p, known_ids=known)

	old1 = rotated_transcript_path(p)
	assert old1.is_file(), "超过上限应产生归档"
	assert p.is_file()
	assert p.stat().st_size <= 1500 + 300, "当前文件应从轮转点重新开始"

	# 跨归档读取：单次轮转下全部消息按序恢复
	loaded = messages_from_transcript(p)
	assert [m.content for m in loaded] == [m.content for m in msgs]
	ids = _load_written_ids(p)
	assert {m.id for m in msgs} <= ids


def test_multi_generation_rotation_preserves_order_when_archives_fill(tmp_path, monkeypatch):
	"""Two full archive slots stop rotation and retain all rows."""
	monkeypatch.setenv("XEYO_TRANSCRIPT_MAX_BYTES", "1200")
	p = tmp_path / "s.jsonl"
	msgs = [user_message(f"m{i} " + "y" * 90) for i in range(40)]
	known: set[str] = set()
	for m in msgs:
		record_transcript_sync([m], session_id="s", path=p, known_ids=known)

	olds = [q for q in rotated_transcript_paths(p) if q.is_file()]
	assert olds, "多次超限应产生归档链"
	rows = []
	for f in transcript_read_paths(p):
		import json

		for line in f.read_text(encoding="utf-8").splitlines():
			if line.strip():
				rows.append(json.loads(line))

	contents = [r["content"] for r in rows]
	# When both archive slots are full, rotation stops and the current file stays appendable.
	assert contents == [m.content for m in msgs], "rotation preserves every row in source order"
	assert contents[-1] == msgs[-1].content, "the latest message remains in the current file"


def test_under_limit_no_archive(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_TRANSCRIPT_MAX_BYTES", "1000000")
	p = tmp_path / "t.jsonl"
	record_transcript_sync(
		[user_message("hello")], session_id="t", path=p, known_ids=set()
	)
	assert not any(q.is_file() for q in rotated_transcript_paths(p))
	assert transcript_read_paths(p) == [p]


def test_rotation_preserves_archive_generations_and_stops_when_full(tmp_path, monkeypatch):
	"""Existing archives move older before current becomes old1."""
	import json

	from session.record_transcript import _maybe_rotate

	monkeypatch.setenv("XEYO_TRANSCRIPT_MAX_BYTES", "1024")
	p = tmp_path / "generations.jsonl"
	rows = []
	for name in ("first", "second", "third"):
		row = {"id": name, "role": "user", "content": name + "x" * 1100}
		rows.append(row)
		p.write_text(json.dumps(row) + "\n", encoding="utf-8")
		_maybe_rotate(p)

	old2, old1 = rotated_transcript_paths(p)
	assert json.loads(old2.read_text(encoding="utf-8")) == rows[0]
	assert json.loads(old1.read_text(encoding="utf-8")) == rows[1]
	assert json.loads(p.read_text(encoding="utf-8")) == rows[2]


def test_flush_pending_drains_background_writes(tmp_path):
	from session.record_transcript import flush_pending_sync, submit_async_append

	p = tmp_path / "bg.jsonl"
	submit_async_append(str(p), ['{"id": "a", "role": "user"}\n'] * 5)
	assert flush_pending_sync(timeout=5.0) is True
	assert p.is_file()
	assert len(p.read_text(encoding="utf-8").splitlines()) == 5
