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


def test_applies_to_roundtrips_as_a_nonempty_list(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	note = parse_and_validate(
		{
			"id": "mem_applies_to",
			"type": "feedback",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "active",
			"scope": "workspace",
			"applies_to": ["src/**", {"path": "tests/**", "reason": "test"}],
			"title": "applies to",
		},
		"body",
	)
	write_note(note, wsid=wsid)
	assert [loaded for loaded in load_notes(wsid) if loaded.id == note.id] == [note]


def test_same_title_slug_keeps_distinct_note_ids(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	base = {
		"type": "feedback",
		"source": {"kind": "user"},
		"confidence": 1.0,
		"status": "active",
		"scope": "workspace",
	}
	first = parse_and_validate({**base, "id": "mem_first", "title": "科学"}, "first")
	second = parse_and_validate({**base, "id": "mem_second", "title": "哲学"}, "second")
	write_note(first, wsid=wsid)
	write_note(second, wsid=wsid)
	assert {note.id for note in load_notes(wsid)} == {first.id, second.id}


def test_frontmatter_escaped_strings_roundtrip(tmp_path, monkeypatch):
	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	title = 'quoted "title" with \\\\ and\nnext line'
	note = parse_and_validate(
		{
			"id": "mem_escaped",
			"type": "feedback",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "active",
			"scope": "workspace",
			"title": title,
		},
		"body",
	)
	write_note(note, wsid=wsid)
	assert next(loaded for loaded in load_notes(wsid) if loaded.id == note.id).title == title


def test_legacy_title_migration_is_identity_scoped(tmp_path, monkeypatch):
	from dataclasses import replace

	from memory.governance import note_to_frontmatter
	from memory.memdir import dump_frontmatter, memdir_root, topic_filename

	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	base = {
		"type": "feedback",
		"source": {"kind": "user"},
		"confidence": 1.0,
		"status": "active",
		"scope": "workspace",
	}
	legacy = parse_and_validate({**base, "id": "mem_legacy", "title": "legacy title"}, "old body")
	other = parse_and_validate({**base, "id": "mem_other", "title": "new shared title"}, "other body")
	topics = memdir_root(wsid) / "topics"
	topics.mkdir(parents=True, exist_ok=True)
	legacy_path = topics / "feedback-legacy-title.md"
	other_path = topics / "feedback-new-shared-title.md"
	legacy_path.write_text(dump_frontmatter(note_to_frontmatter(legacy)) + "\nold body\n", encoding="utf-8")
	other_path.write_text(dump_frontmatter(note_to_frontmatter(other)) + "\nother body\n", encoding="utf-8")
	rewrite_index([legacy, other], wsid=wsid)
	assert "topics/feedback-legacy-title.md" in load_index_text(wsid)
	assert "topics/feedback-new-shared-title.md" in load_index_text(wsid)

	updated = replace(legacy, title="new shared title", content="updated body")
	new_path = write_note(updated, wsid=wsid)
	assert new_path.is_file()
	assert not legacy_path.exists()
	assert other_path.read_text(encoding="utf-8").endswith("other body\n")
	index = load_index_text(wsid)
	assert f"topics/{new_path.name}" in index
	assert "topics/feedback-legacy-title.md" not in index
	assert "topics/feedback-new-shared-title.md" in index
	assert {note.id for note in load_notes(wsid)} == {legacy.id, other.id}
	assert next(note for note in load_notes(wsid) if note.id == legacy.id).content == "updated body"
	assert new_path.name == topic_filename(updated)


def test_legacy_file_survives_failed_identity_migration(tmp_path, monkeypatch):
	from dataclasses import replace

	import pytest
	import memory.memdir as memdir
	from memory.governance import note_to_frontmatter

	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	note = parse_and_validate(
		{
			"id": "mem_interrupted",
			"type": "feedback",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "active",
			"scope": "workspace",
			"title": "old title",
		},
		"old body",
	)
	legacy = memdir.memdir_root(wsid) / "topics" / "feedback-old-title.md"
	legacy.parent.mkdir(parents=True, exist_ok=True)
	legacy.write_text(memdir.dump_frontmatter(note_to_frontmatter(note)) + "\nold body\n", encoding="utf-8")
	rewrite_index([note], wsid=wsid)
	assert "topics/feedback-old-title.md" in load_index_text(wsid)
	before = legacy.read_bytes()
	updated = replace(note, title="new title")
	new_path = memdir.memdir_root(wsid) / "topics" / memdir.topic_filename(updated)
	original_replace = memdir.os.replace

	def fail_publish(source, destination):
		if Path(destination) == new_path:
			raise OSError("simulated publish interruption")
		return original_replace(source, destination)

	monkeypatch.setattr(memdir.os, "replace", fail_publish)
	with pytest.raises(OSError, match="simulated publish interruption"):
		write_note(replace(updated, content="new body"), wsid=wsid)
	assert legacy.read_bytes() == before
	assert not new_path.exists()
	assert "topics/feedback-old-title.md" in load_index_text(wsid)


def test_legacy_file_survives_failed_index_migration(tmp_path, monkeypatch):
	from dataclasses import replace

	import pytest
	import memory.memdir as memdir
	from memory.governance import note_to_frontmatter

	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	note = parse_and_validate(
		{
			"id": "mem_index_interrupted",
			"type": "feedback",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "active",
			"scope": "workspace",
			"title": "old title",
		},
		"old body",
	)
	legacy = memdir.memdir_root(wsid) / "topics" / "feedback-old-title.md"
	legacy.parent.mkdir(parents=True, exist_ok=True)
	legacy.write_text(memdir.dump_frontmatter(note_to_frontmatter(note)) + "\nold body\n", encoding="utf-8")
	rewrite_index([note], wsid=wsid)
	index_before = load_index_text(wsid)
	legacy_before = legacy.read_bytes()
	updated = replace(note, title="new title", content="new body")
	new_path = memdir.memdir_root(wsid) / "topics" / memdir.topic_filename(updated)
	original_replace = memdir.os.replace

	def fail_index_replace(source, destination):
		if Path(destination) == memdir.memdir_root(wsid) / "MEMORY.md":
			raise OSError("simulated index migration interruption")
		return original_replace(source, destination)

	monkeypatch.setattr(memdir.os, "replace", fail_index_replace)
	with pytest.raises(OSError, match="simulated index migration interruption"):
		write_note(updated, wsid=wsid)
	assert new_path.is_file()
	assert legacy.read_bytes() == legacy_before
	assert load_index_text(wsid) == index_before
	loaded = [loaded for loaded in load_notes(wsid) if loaded.id == note.id]
	assert len(loaded) == 1
	assert loaded[0].content == "new body"


def test_note_write_rejects_identity_collision_without_overwrite(tmp_path, monkeypatch):
	import pytest

	from memory.governance import MemorySchemaError, note_to_frontmatter
	from memory.memdir import dump_frontmatter, memdir_root, topic_filename

	root = _ws(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	base = {
		"type": "feedback",
		"source": {"kind": "user"},
		"confidence": 1.0,
		"status": "active",
		"scope": "workspace",
	}
	note = parse_and_validate({**base, "id": "mem_expected", "title": "expected"}, "new")
	other = parse_and_validate({**base, "id": "mem_wrong", "title": "wrong"}, "existing")
	path = memdir_root(wsid) / "topics" / topic_filename(note)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(dump_frontmatter(note_to_frontmatter(other)) + "\nexisting\n", encoding="utf-8")
	before = path.read_bytes()
	with pytest.raises(MemorySchemaError, match="topic_identity_conflict"):
		write_note(note, wsid=wsid)
	assert path.read_bytes() == before
