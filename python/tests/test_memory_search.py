"""memory.search 词法检索（引擎层直测；工具入口已收敛为 Grep 直读 + Memory 写路径）。"""

from __future__ import annotations

import asyncio

from engine.abort import AbortController
from memory.search import search
from tools.memory_tool import MemoryTool


def test_search_finds_written_note(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	write = MemoryTool(cwd=str(root))
	out = asyncio.run(
		write.execute(
			{
				"action": "write",
				"type": "feedback",
				"content": "测试必须打真库",
				"title": "真实 DB",
				"source_kind": "user",
			},
			AbortController(),
		)
	)
	assert not out.is_error
	hits = search("真库", cwd=str(root), scope="workspace")
	assert hits and hits[0].title == "真实 DB"
	assert search("不存在的词xyzzy", cwd=str(root), scope="workspace") == []


def test_search_cjk_bigram_or(tmp_path, monkeypatch):
	"""无空格中文查询用 bigram OR，避免整串匹配失败。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	write = MemoryTool(cwd=str(root))
	out = asyncio.run(
		write.execute(
			{
				"action": "write",
				"type": "user",
				"content": "习惯中文简短回复，不要用 Markdown 大标题堆砌",
				"title": "回复习惯",
				"scope": "user",
				"source_kind": "user",
			},
			AbortController(),
		)
	)
	assert not out.is_error
	hits = search("回复语言偏好", cwd=str(root), scope="user", touch=False)
	assert hits and hits[0].title == "回复习惯"


def test_search_note_citation_anchor(tmp_path, monkeypatch):
	"""P1-1 检索命中带 notes/topics/*.md:行区间 + rollout_ids 引用锚点。"""
	from memory.memdir import workspace_id
	from memory.search import note_citation_text

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	write = MemoryTool(cwd=str(root))
	out = asyncio.run(
		write.execute(
			{
				"action": "write",
				"type": "feedback",
				"content": "测试必须打真库",
				"title": "真实 DB",
				"source_kind": "user",
				"session_id": "sess_cite",
			},
			AbortController(),
		)
	)
	assert not out.is_error
	hits = search("真库", cwd=str(root), scope="workspace", touch=False)
	assert hits
	cite = note_citation_text(hits[0], workspace_id(str(root)))
	assert "<citation_entries>" in cite
	assert "<rollout_ids>" in cite
	assert "notes/topics/feedback-" in cite
	assert "sess_cite" in cite
