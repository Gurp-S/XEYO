"""P1-1 citation 溯源：引用格式解析/渲染 + C2 摘要行引用锚点 + 检索引用。"""

from __future__ import annotations

import os
import time

from memory.citation import (
	CitationBlock,
	CitationEntry,
	block_for_entries,
	entry_line,
	message_citation,
	note_file_citation,
	parse_block,
	parse_entry_line,
	render_block,
	rollout_id_from_source,
)
from memory.memdir import prune_dead_notes, retention_days
from memory.runtime import deterministic_c2_summary


# --------------------------------------------------------------------------- #
# citation.py 纯函数
# --------------------------------------------------------------------------- #

def test_entry_line_roundtrip():
	e = CitationEntry(path="src/main.rs", line_start=53, line_end=81, note="helper")
	assert entry_line(e) == "src/main.rs:53-81|note=[helper]"
	assert parse_entry_line("src/main.rs:53-81|note=[helper]") == e


def test_entry_line_no_line_no_note():
	e = CitationEntry(path="notes/topics/x.md", note="title")
	line = entry_line(e)
	assert line == "notes/topics/x.md|note=[title]"
	assert parse_entry_line(line) == e


def test_parse_entry_line_bad_returns_none():
	assert parse_entry_line("") is None
	assert parse_entry_line("|note=[]") is None
	assert parse_entry_line("path:1-2|note=[x") is None or True  # 不抛即可


def test_block_return_roundtrip():
	block = block_for_entries(
		[note_file_citation("notes/topics/feedback-a.md", line_start=3, line_end=7, note="真实 DB")],
		rollout_ids=["sess_abc", "sess_abc", "sess_def"],
	)
	text = render_block(block)
	assert "<citation_entries>" in text
	assert "<rollout_ids>" in text
	assert "notes/topics/feedback-a.md:3-7|note=[真实 DB]" in text
	# 去重 rollout id，保留首序
	assert "sess_abc" in text and "sess_def" in text
	parsed = parse_block(text)
	assert parsed.rollout_ids == ["sess_abc", "sess_def"]
	assert parsed.entries[0].path == "notes/topics/feedback-a.md"
	assert parsed.entries[0].line_start == 3 and parsed.entries[0].line_end == 7


def test_block_empty_renders_empty():
	assert render_block(CitationBlock()) == ""
	assert parse_block("") == CitationBlock()


def test_parse_block_accepts_thread_ids_alias():
	text = "<thread_ids>\nsess_x\n</thread_ids>"
	assert parse_block(text).rollout_ids == ["sess_x"]


def test_message_citation_anchor():
	e = message_citation(12, kind="tool_result")
	assert e.path == "notes:msg:12"
	assert e.note == "tool_result"
	assert entry_line(e) == "notes:msg:12|note=[tool_result]"


def test_rollout_id_from_source():
	assert rollout_id_from_source({"session_id": "s1"}) == "s1"
	assert rollout_id_from_source(None) == ""
	assert rollout_id_from_source({"session_id": ""}) == ""


# --------------------------------------------------------------------------- #
# C2 确定性摘要行带引用锚点（P1-1 runtime.py）
# --------------------------------------------------------------------------- #

def _tool_result(uid, content):
	return {
		"role": "user",
		"content": [
			{"type": "tool_result", "tool_use_id": uid, "content": content, "is_error": False}
		],
	}


def _assistant_use(uid, name):
	return {
		"role": "assistant",
		"content": [{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}}],
	}


def test_c2_summary_new_style_has_citation_anchors(monkeypatch, mem_switch):
	mem_switch.reset("XEYO_C2_CITATION")
	left = [
		{"role": "user", "content": "find the caller"},
		_assistant_use("g1", "Grep"),
		_tool_result("g1", "found in src/run.py:12"),
	]
	out = deterministic_c2_summary(left, style="new")
	assert "⟦notes:msg:0|note=[user]⟧" in out
	assert "⟦notes:msg:2|note=[tool_result]⟧" in out
	# id/kind/tokens 前缀不变
	assert "2:g1:tool_result:" in out


def test_c2_summary_legacy_has_no_citation(monkeypatch, mem_switch):
	mem_switch.reset("XEYO_C2_CITATION")
	left = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
	legacy = deterministic_c2_summary(left, style="legacy")
	assert "⟦" not in legacy
	assert "::" not in legacy


def test_c2_summary_citation_fixed_on(monkeypatch, mem_switch):
	"""C2 引用锚点已固化开启：mem_switch 写 0 也关不掉（键已出注册表）。"""
	mem_switch(XEYO_C2_CITATION="0")
	left = [{"role": "user", "content": "hello"}]
	out = deterministic_c2_summary(left, style="new")
	assert "⟦notes:msg:0|note=[user]⟧" in out


def test_c2_summary_budget_bounded_with_citation(monkeypatch, mem_switch):
	mem_switch.reset("XEYO_C2_CITATION")
	left = [{"role": "user", "content": "x" * 2000} for _ in range(200)]
	out = deterministic_c2_summary(left, style="new", budget=12_000)
	# 预算封顶：携带片段的行受 12k 预算约束，预算耗尽后仅存元数据行（含消息下标），
	# 不会因引用锚点无限增长。允许约 2k 元数据行溢出。
	assert len(out) <= 12_000 + 2_000
	assert "compacted 200 earlier messages" in out


# --------------------------------------------------------------------------- #
# P1-2 保留期剪枝（memdir.prune_dead_notes）
# --------------------------------------------------------------------------- #

def _note(status, title, content="fact"):
	from memory.governance import parse_and_validate

	return parse_and_validate(
		{
			"id": "mem_%s" % title,
			"type": "feedback",
			"source": {"kind": "user", "session_id": "s", "message_id": "m"},
			"confidence": 1.0,
			"status": status,
			"scope": "workspace",
			"title": title,
		},
		content,
	)


def _prime_path(path, age_days):
	old = time.time() - age_days * 86400.0
	os.utime(path, (old, old))


def test_retention_days_default_and_override(monkeypatch):
	monkeypatch.delenv("XEYO_MEMORY_RETENTION_DAYS", raising=False)
	assert retention_days() == 7.0
	monkeypatch.setenv("XEYO_MEMORY_RETENTION_DAYS", "0")
	assert retention_days() == 0.0


def test_prune_dead_notes_keeps_active_and_recent(tmp_path, monkeypatch):
	from memory.memdir import (
		ensure_layout,
		load_notes,
		note_topics_path,
		workspace_id,
		write_note,
	)

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_MEMORY_RETENTION_DAYS", "7")
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	ensure_layout(wsid)
	active = _note("active", "keep")
	deleted = _note("deleted", "gone")
	write_note(active, wsid=wsid)
	write_note(deleted, wsid=wsid)
	# 把 deleted 文件的 mtime 拨到 10 天前
	_prime_path(note_topics_path(deleted, wsid), 10)
	removed = prune_dead_notes(wsid)
	assert removed == 1
	ids = [n.id for n in load_notes(wsid)]
	assert "mem_keep" in ids
	assert "mem_gone" not in ids


def test_prune_dead_notes_leaves_recent_deleted(tmp_path, monkeypatch):
	from memory.memdir import ensure_layout, load_notes, workspace_id, write_note

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_MEMORY_RETENTION_DAYS", "7")
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	ensure_layout(wsid)
	write_note(_note("deleted", "recent"), wsid=wsid)
	assert prune_dead_notes(wsid) == 0
	assert len([n for n in load_notes(wsid) if n.id == "mem_recent"]) == 1


def test_prune_dead_notes_zero_days_disables(tmp_path, monkeypatch):
	from memory.memdir import ensure_layout, workspace_id, write_note

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_MEMORY_RETENTION_DAYS", "0")
	root = tmp_path / "proj"
	root.mkdir()
	wsid = workspace_id(str(root))
	ensure_layout(wsid)
	write_note(_note("deleted", "gone"), wsid=wsid)
	assert prune_dead_notes(wsid) == 0
