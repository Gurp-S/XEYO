"""memdir 布局、索引、Forget、复制目录新 id。"""

from __future__ import annotations

from pathlib import Path

from engine.abort import AbortController
from memory.governance import parse_and_validate
from memory.memdir import (
	is_under_memdir,
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


def test_copy_dir_gets_new_workspace_id(tmp_path, monkeypatch):
	a = _ws(tmp_path, monkeypatch, "a")
	b = tmp_path / "b"
	b.mkdir()
	assert workspace_id(str(a)) != workspace_id(str(b))


def test_write_then_index_then_forget(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	tool = MemoryTool(cwd=str(root))
	# execute is async
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
