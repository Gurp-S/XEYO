"""子 Agent 元数据持久化（多 Agent UI 数据源）边界测试。

覆盖：upsert/list 排序、字段归一化、has_transcript 自动探测、
侧链 transcript 往返、空目录幂等。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from engine.subagent_runner import (  # noqa: E402
	_meta_path,
	list_subagent_metas,
	load_sidechain_messages,
	upsert_subagent_meta,
)
from msgtypes.message import Message, user_message  # noqa: E402
from session.record_transcript import record_transcript_sync  # noqa: E402


def test_upsert_and_list_sorted_by_start(tmp_path, monkeypatch):
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	upsert_subagent_meta("s1", agent_id="agent-b", task_desc="任务B", status="done",
						 task_id="tb", started_at=200.0, finished_at=210.0, result_preview="ok")
	upsert_subagent_meta("s1", agent_id="agent-a", task_desc="任务A", status="error",
						 task_id="ta", started_at=100.0, finished_at=150.0, result_preview="")
	metas = list_subagent_metas("s1")
	assert [m["agent_id"] for m in metas] == ["agent-a", "agent-b"]
	b = metas[1]
	assert b["status"] == "done"
	assert b["task_desc"] == "任务B"
	assert b["task_id"] == "tb"
	assert b["started_at"] == 200.0 and b["finished_at"] == 210.0
	assert isinstance(b["has_transcript"], bool)


def test_upsert_truncates_long_fields(tmp_path, monkeypatch):
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	upsert_subagent_meta(
		"s2", agent_id="agent-x",
		task_desc="长" * 500, status="done",
		result_preview="尾" * 800,
	)
	meta = list_subagent_metas("s2")[0]
	assert len(meta["task_desc"]) == 200
	assert len(meta["result_preview"]) == 400


def test_has_transcript_auto_detected(tmp_path, monkeypatch):
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	upsert_subagent_meta("s3", agent_id="agent-t", task_desc="t", status="done")
	assert list_subagent_metas("s3")[0]["has_transcript"] is False

	msgs = [user_message("hi"), Message(role="assistant", content="hello")]
	n = record_transcript_sync(msgs, session_id="unused", path=_meta_path("s3", "agent-t").parent / "agent-t.jsonl")
	assert n == 2

	upsert_subagent_meta("s3", agent_id="agent-t", task_desc="t", status="done")
	assert list_subagent_metas("s3")[0]["has_transcript"] is True


def test_load_sidechain_roundtrip(tmp_path, monkeypatch):
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	p = _meta_path("s4", "agent-r").parent / "agent-r.jsonl"
	rows = [
		user_message("拆分 util.py"),
		Message(role="assistant", content=[
			{"type": "text", "text": "先读再写"},
			{"type": "image_url", "image_url": {"url": "xeyo-media://ff"}},
		]),
		Message(role="tool", content="ok", name="Read", tool_call_id="c1"),
	]
	record_transcript_sync(rows, session_id="unused", path=p)
	out = load_sidechain_messages("s4", "agent-r")
	assert len(out) == 3
	assert out[0]["role"] == "user" and out[0]["content"] == "拆分 util.py"
	assert out[1]["role"] == "assistant" and isinstance(out[1]["content"], list)
	assert out[2]["role"] == "tool" and out[2]["name"] == "Read"


def test_list_missing_dir_empty(tmp_path, monkeypatch):
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	assert list_subagent_metas("nope") == []


def test_corrupt_meta_file_skipped(tmp_path, monkeypatch):
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	d = _meta_path("s5", "agent-ok").parent
	d.mkdir(parents=True, exist_ok=True)
	(d / "broken.meta.json").write_text("{not json", encoding="utf-8")
	upsert_subagent_meta("s5", agent_id="agent-ok", task_desc="good", status="done")
	metas = list_subagent_metas("s5")
	assert len(metas) == 1 and metas[0]["agent_id"] == "agent-ok"


def test_status_normalization_in_runner_helper(tmp_path, monkeypatch):
	"""upsert 不改写 status 原值（runner 侧负责 done/error/stopped 归一）。"""
	monkeypatch.setenv("USERPROFILE", str(tmp_path))
	monkeypatch.setenv("HOME", str(tmp_path))
	upsert_subagent_meta("s6", agent_id="a", task_desc="d", status="stopped")
	meta = json.loads(_meta_path("s6", "a").read_text(encoding="utf-8"))
	assert meta["status"] == "stopped"
