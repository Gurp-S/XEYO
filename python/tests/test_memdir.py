"""memdir 布局、索引、Forget、复制目录新 id。"""

from __future__ import annotations

from pathlib import Path

from engine.abort import AbortController
from memory.governance import parse_and_validate
from memory.memdir import (
	load_index_text,
	load_notes,
	rewrite_index,
	workspace_id,
	write_note,
)
from permissions.gate import can_use_tool
from tools.memory_tool import MemoryTool


def _ws(tmp_path: Path, monkeypatch, name: str = "proj") -> Path:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / name
	root.mkdir()
	return root


def test_touch_last_used_does_not_resurrect_deleted(tmp_path, monkeypatch):
	"""2026-10-05：检索触达持有的陈旧对象，写前必须重读磁盘——不得复活已删笔记。"""
	import asyncio
	from dataclasses import replace as _replace

	from memory.memdir import touch_last_used

	root = _ws(tmp_path, monkeypatch)
	tool = MemoryTool(cwd=str(root))
	out = asyncio.run(
		tool.execute(
			{
				"action": "write",
				"type": "feedback",
				"content": "检索命中会被 touch",
				"title": "触达回归",
				"source_kind": "user",
				"confidence": 1.0,
			},
			AbortController(),
		)
	)
	assert not out.is_error
	wsid = workspace_id(str(root))
	stale = [n for n in load_notes(wsid) if n.title == "触达回归"][0]
	assert stale.status == "active"

	# 模拟并行 forget：磁盘上已改为 deleted（此后 stale 对象即过期快照）
	write_note(_replace(stale, status="deleted"), wsid=wsid)

	touch_last_used(stale, wsid=wsid)

	after = [n for n in load_notes(wsid) if n.id == stale.id]
	assert after and after[0].status == "deleted", "陈旧触达复活了已删笔记"


def test_touch_last_used_updates_active_note(tmp_path, monkeypatch):
	"""方向控制：active 笔记照常更新 last_used_at（与新守卫共存）。"""
	import asyncio

	from memory.memdir import touch_last_used

	root = _ws(tmp_path, monkeypatch)
	tool = MemoryTool(cwd=str(root))
	out = asyncio.run(
		tool.execute(
			{
				"action": "write",
				"type": "feedback",
				"content": "正常触达",
				"title": "正常触达",
				"source_kind": "user",
				"confidence": 1.0,
			},
			AbortController(),
		)
	)
	assert not out.is_error
	wsid = workspace_id(str(root))
	note = [n for n in load_notes(wsid) if n.title == "正常触达"][0]
	assert not note.last_used_at

	touched = touch_last_used(note, wsid=wsid)

	assert touched.last_used_at, "active 笔记的 last_used_at 应被更新"
	after = [n for n in load_notes(wsid) if n.id == note.id][0]
	assert after.last_used_at == touched.last_used_at


def test_copy_dir_gets_new_workspace_id(tmp_path, monkeypatch):
	a = _ws(tmp_path, monkeypatch, "a")
	b = tmp_path / "b"
	b.mkdir()
	assert workspace_id(str(a)) != workspace_id(str(b))


def test_write_then_index_then_forget(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	tool = MemoryTool(cwd=str(root))
	# execute 是异步的
	import asyncio

	out = asyncio.run(
		tool.execute(
			{
				"action": "write",
				"type": "feedback",
				"content": "测试必须打真库",
				"title": "测试必须用真实 DB",
				"source_kind": "user",
				"confidence": 1.0,
			},
			AbortController(),
		)
	)
	assert not out.is_error
	wsid = workspace_id(str(root))
	idx = load_index_text(wsid)
	assert "[feedback]" in idx
	assert "topics/" in idx
	assert "测试必须" in idx
	# 索引不含叙事长文
	assert "mock" not in idx.lower() or "真实" in idx
	notes = load_notes(wsid)
	assert len(notes) == 1
	note_id = notes[0].id
	fout = asyncio.run(
		tool.execute({"action": "forget", "id": note_id, "reason": "user_request"}, AbortController())
	)
	assert not fout.is_error
	idx2 = load_index_text(wsid)
	assert note_id not in idx2
	assert "真实 DB" not in idx2
	assert load_notes(wsid)[0].status == "deleted"


def test_index_bytes_stable_without_mutation(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	note = parse_and_validate(
		{
			"id": "mem_stable",
			"type": "feedback",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "active",
			"scope": "workspace",
			"title": "stable",
		},
		"body",
	)
	write_note(note, wsid=wsid)
	rewrite_index([note], wsid=wsid)
	a = load_index_text(wsid)
	b = load_index_text(wsid)
	assert a == b
	assert a.encode("utf-8") == b.encode("utf-8")


def test_write_escape_memdir_denied(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	cwd = str(root)
	other = tmp_path / "other" / ".xeyo" / "memory" / "x"
	other.mkdir(parents=True)
	target = str(other / "evil.md")
	gate = can_use_tool("Write", {"file_path": target, "content": "x"}, cwd=cwd)
	# 不在本工作区 memdir，也不在 cwd → deny
	assert not gate.allowed


def test_write_memdir_missing_schema_denied(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	from memory.memdir import memdir_root

	path = str(memdir_root(wsid) / "topics" / "x.md")
	gate = can_use_tool(
		"Write",
		{"file_path": path, "content": "no frontmatter"},
		cwd=str(root),
	)
	assert not gate.allowed
	assert gate.reason == "memdir_schema_rejected"
