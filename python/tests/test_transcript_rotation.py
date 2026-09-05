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


def test_multi_generation_rotation_bounded_and_ordered(tmp_path, monkeypatch):
	"""多代轮转：只保留最近 2 代归档 + 当前；可恢复部分必须保序且含最新消息。"""
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
	# 保序子序列（老代被淘汰，但不乱序、不重复）
	all_contents = [m.content for m in msgs]
	j = 0
	for c in contents:
		while j < len(all_contents) and all_contents[j] != c:
			j += 1
		assert j < len(all_contents), f"消息 {c[:12]!r} 乱序或不存在"
		j += 1
	assert contents[-1] == msgs[-1].content, "最新消息必须在当前文件中"
	assert len(rows) < len(msgs), "超出保留代数的旧消息被淘汰"


def test_under_limit_no_archive(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_TRANSCRIPT_MAX_BYTES", "1000000")
	p = tmp_path / "t.jsonl"
	record_transcript_sync(
		[user_message("hello")], session_id="t", path=p, known_ids=set()
	)
	assert not any(q.is_file() for q in rotated_transcript_paths(p))
	assert transcript_read_paths(p) == [p]


def test_flush_pending_drains_background_writes(tmp_path):
	from session.record_transcript import flush_pending_sync, submit_async_append

	p = tmp_path / "bg.jsonl"
	submit_async_append(str(p), ['{"id": "a", "role": "user"}\n'] * 5)
	assert flush_pending_sync(timeout=5.0) is True
	assert p.is_file()
	assert len(p.read_text(encoding="utf-8").splitlines()) == 5