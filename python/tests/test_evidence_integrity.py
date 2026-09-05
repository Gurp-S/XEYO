"""T28 证据完整性回归：journal 失败可观测；过程旁白留档（background only）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.process_narration import (
	StreamNarrationGate,
	split_process_narration,
	strip_process_narration,
)
from msgtypes.message import assistant_text_message
from session.hydrate import message_from_row
from session.record_transcript import message_to_dict
from session.transcript_blobs import row_from_message


# ---------- journal 失败显式化 ----------


@pytest.mark.asyncio
async def test_write_tool_surfaces_journal_warning(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
	from engine.write_store import WriteStore
	from tools.file_write_tool import FileWriteTool

	ws = tmp_path / "ws"
	ws.mkdir()
	(target := ws / "note.txt").write_text("hello", encoding="utf-8")
	store = WriteStore(root=str(ws))
	tool = FileWriteTool(cwd=str(ws))
	tool.set_write_store(store)
	tool.set_read_file_state(_FakeReadState(target))  # type: ignore[attr-defined]

	def _boom(*_a: object, **_k: object) -> None:
		raise OSError("journal disk full")

	monkeypatch.setattr("memory.journal.record_change", _boom)
	with caplog.at_level("ERROR", logger="xeyo.write_store.journal"):
		res = await tool.execute(
			{"file_path": str(target), "content": "hello\nworld\n"}, __import__("engine.abort", fromlist=["AbortController"]).AbortController()
		)
	assert not res.is_error  # 文件已落盘，不假报错
	assert "[journal]" in res.content  # 但警示必须可见
	assert any("journal" in (r.getMessage() or "") for r in caplog.records)


class _FakeReadState:
	"""最小 read_state 桩：提供 base 哈希与 set_written。"""

	def __init__(self, path: Path) -> None:
		self._path = str(path)

	def get(self, _path: str):  # noqa: ANN201
		from types import SimpleNamespace

		from engine.write_store import _content_hash_text

		content = Path(self._path).read_text(encoding="utf-8")
		return SimpleNamespace(
			content=content,
			mtime_ms=0,
			offset=None,
			limit=None,
			content_known=True,
			is_partial_view=False,
			timestamp=0,
			_base_hash=_content_hash_text(content),
		)

	def set_written(self, *_a: object, **_k: object) -> None:
		return None


# ---------- 过程旁白留档 ----------


def test_split_narration_keeps_both_parts() -> None:
	raw = "让我看看相关代码。\n\n真正结论在这里。"
	body, narr = split_process_narration(raw)
	assert body == "真正结论在这里。"
	assert "让我看看" in narr
	# strip 语义不变（回归保护）
	assert strip_process_narration(raw) == "真正结论在这里。"


def test_narration_roundtrips_through_transcript_row(tmp_path: Path) -> None:
	msg = assistant_text_message("结论正文", narration="让我查看文件。")
	row = message_to_dict(msg)
	assert row.get("narration") == "让我查看文件。"
	back = message_from_row(row)
	assert back is not None
	assert back.narration == "让我查看文件。"  # 还原原文
	# blob 行同样携带
	row2 = row_from_message(msg, anchor=tmp_path)
	assert row2.get("narration") == "让我查看文件。"


def test_narration_absent_when_empty() -> None:
	msg = assistant_text_message("正文")
	assert message_to_dict(msg).get("narration", "") == ""
	assert assistant_text_message("正文").narration == ""


def test_gate_drains_narration_once() -> None:
	gate = StreamNarrationGate()
	gate.on_delta("让我看看。\n\n")
	gate.on_delta("结论。")
	body, _flush = gate.finish(has_tools=True)
	assert body == "结论。"
	narr = gate.drain_narration()
	assert "让我看看" in narr
	assert gate.drain_narration() == ""  # 取走即清
