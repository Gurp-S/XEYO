from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msgtypes.message import user_message, assistant_text_message
from session.record_transcript import (
	load_transcript,
	record_transcript_sync,
)


def test_record_transcript_appends_and_dedupes(tmp_path: Path):
	sid = "testsession"
	path = tmp_path / f"{sid}.jsonl"
	m1 = user_message("hello")
	m2 = assistant_text_message("hi")
	known: set[str] = set()

	n1 = record_transcript_sync(
		[m1, m2],
		session_id=sid,
		path=path,
		known_ids=known,
	)
	assert n1 == 2
	assert path.is_file()

	n2 = record_transcript_sync(
		[m1, m2],
		session_id=sid,
		path=path,
		known_ids=known,
	)
	assert n2 == 0

	rows = load_transcript(path)
	assert len(rows) == 2
	assert rows[0]["role"] == "user"
	assert rows[0]["content"] == "hello"


def test_persist_disabled(tmp_path: Path):
	path = tmp_path / "x.jsonl"
	m = user_message("nope")
	n = record_transcript_sync(
		[m],
		session_id="s",
		path=path,
		session_persistence_disabled=True,
	)
	assert n == 0
	assert not path.exists()


def test_known_ids_cache_avoids_rescan(tmp_path: Path):
	path = tmp_path / "s.jsonl"
	m1 = user_message("one")
	known: set[str] = set()
	record_transcript_sync([m1], session_id="s", path=path, known_ids=known)
	assert m1.id in known

	m2 = assistant_text_message("two")
	# 复用同一 known 集合，不应重复写入 m1
	n = record_transcript_sync([m1, m2], session_id="s", path=path, known_ids=known)
	assert n == 1
	assert len(load_transcript(path)) == 2


def test_record_ui_thoughts_sync(tmp_path: Path):
	path = tmp_path / "t.jsonl"
	known: set[str] = set()

	async def _run() -> int:
		from session.record_transcript import record_ui_thoughts

		return await record_ui_thoughts(
			[{"id": "thought-1", "text": "reasoning", "thought_ms": 900}],
			session_id="sess",
			path=path,
			known_ids=known,
		)

	import asyncio
	from session.record_transcript import flush_pending_sync

	written = asyncio.run(_run())
	assert written == 1
	assert "thought-1" in known
	flush_pending_sync()
	rows = load_transcript(path)
	assert rows[0]["role"] == "ui_thought"
	assert rows[0]["content"] == "reasoning"
