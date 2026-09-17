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


def test_sync_write_preserves_order_after_async_write(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
	"""同步 T_now 留痕不能插到后台写入的工具结果中间。"""
	import asyncio
	import importlib
	import threading

	from msgtypes.message import ToolUse, system_note, tool_result_message
	transcript = importlib.import_module("session.record_transcript")

	path = tmp_path / "ordered.jsonl"
	known: set[str] = set()
	assistant = assistant_text_message(
		"",
		[
			ToolUse(id="call-1", name="Read", input={}),
			ToolUse(id="call-2", name="Grep", input={}),
		],
	)
	first = tool_result_message("call-1", "Read", "first")
	second = tool_result_message("call-2", "Grep", "second")

	# 把首批后台写入卡在真正写盘前，确定性地制造旧实现的竞态窗口。
	entered = threading.Event()
	release = threading.Event()
	original_write_batch = transcript._write_batch

	def blocked_write_batch(batch):
		entered.set()
		if not release.wait(5):
			raise AssertionError("test writer was not released")
		original_write_batch(batch)

	monkeypatch.setattr(transcript, "_write_batch", blocked_write_batch)
	try:
		asyncio.run(
			transcript.record_transcript(
				[assistant, first], session_id="s", path=path, known_ids=known
			)
		)
		assert entered.wait(5)

		done = threading.Event()
		errors: list[BaseException] = []

		def sync_write():
			try:
				transcript.record_transcript_sync(
					[system_note("state", key="state", fp="fp")],
					session_id="s",
					path=path,
					known_ids=known,
				)
			except BaseException as exc:  # noqa: BLE001
				errors.append(exc)
			finally:
				done.set()

		thread = threading.Thread(target=sync_write)
		thread.start()
		try:
			# 同步行必须排在首批后台行之后，不能绕过队列直写。
			assert not done.wait(0.1)
		finally:
			release.set()
		assert done.wait(5)
		thread.join(5)
		assert not errors

		asyncio.run(
			transcript.record_transcript(
				[second], session_id="s", path=path, known_ids=known
			)
		)
		assert transcript.flush_pending_sync()
	finally:
		release.set()

	rows = load_transcript(path)
	assert [row["role"] for row in rows] == ["assistant", "tool", "system", "tool"]


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
