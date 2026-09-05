"""Memory 三合一工具（write/update/forget）回归：路由、校验、存储语义不变。"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from memory.memdir import load_notes, load_tombstones, workspace_id
from tools.catalog import build_default_registry


@pytest.fixture()
def env(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "home" / "memory"))
	proj = tmp_path / "proj"
	proj.mkdir()
	return proj


def _tool(proj):
	reg = build_default_registry(cwd=str(proj))
	return reg.get("Memory")


@pytest.mark.asyncio
async def test_registered_and_others_absent(env):
	reg = build_default_registry(cwd=str(env))
	names = {s["name"] for s in reg.schemas()}
	assert "Memory" in names
	for gone in ("MemoryWrite", "MemoryUpdate", "MemoryForget", "MemorySearch"):
		assert gone not in names


@pytest.mark.asyncio
async def test_unknown_action_rejected(env):
	out = await _tool(env).execute({"action": "merge"}, AbortController())
	assert out.is_error and "unknown action" in out.content


@pytest.mark.asyncio
async def test_update_forget_require_id(env):
	t = _tool(env)
	for action in ("update", "forget"):
		out = await t.execute({"action": action}, AbortController())
		assert out.is_error and f"action={action} requires id" in out.content


@pytest.mark.asyncio
async def test_write_then_update_then_forget_roundtrip(env):
	t = _tool(env)
	abort = AbortController()

	r1 = await t.execute(
		{"action": "write", "type": "feedback", "content": "测试必须打真库",
		 "title": "真实DB", "source_kind": "user"},
		abort,
	)
	assert not r1.is_error
	wsid = workspace_id(str(env))
	note_id = [n for n in load_notes(wsid) if n.status == "active"][0].id

	r2 = await t.execute(
		{"action": "update", "id": note_id, "content": "测试必须打真库（更新）"}, abort
	)
	assert not r2.is_error
	active = [n for n in load_notes(wsid) if n.status == "active"]
	assert len(active) == 1 and "更新" in active[0].content

	r3 = await t.execute({"action": "forget", "id": note_id}, abort)
	assert not r3.is_error
	assert any(s.id == note_id for s in load_tombstones(wsid))
	assert all(n.status != "active" for n in load_notes(wsid))


@pytest.mark.asyncio
async def test_tombstone_blocks_resurrect(env):
	t = _tool(env)
	abort = AbortController()
	await t.execute(
		{"action": "write", "type": "user", "content": "偏好中文回复",
		 "title": "语言", "source_kind": "user"},
		abort,
	)
	wsid = workspace_id(str(env))
	note_id = [n for n in load_notes(wsid) if n.status == "active"][0].id
	await t.execute({"action": "forget", "id": note_id}, abort)

	# 同 id 复活被 tombstone 拦截
	r = await t.execute(
		{"action": "write", "id": note_id, "type": "user",
		 "content": "偏好中文回复", "title": "语言"},
		abort,
	)
	assert r.is_error and "tombstone" in r.content


def test_schema_mentions_grep_paths(env):
	schema = _tool(env).schema()
	desc = schema["description"]
	assert "Grep" in desc
	assert "topics/*.md" in desc  # 记忆库路径已注入
	assert "MEMORY.md" in desc  # 索引说明存在；schema 文案已不承诺 transcript 提示


def test_schema_mentions_recall_guidance(env):
	"""批次3：索引不再推送 T_now——召回指引住 description（静态文本）。"""
	desc = _tool(env).schema()["description"]
	assert "prior context" in desc
	assert "call it first before answering" in desc


@pytest.mark.asyncio
async def test_peers_action_schema_and_empty(env):
	"""action=peers：能力宣告住 description；无 peer 返回空（非错误）。"""
	t = _tool(env)
	schema = t.schema()
	assert "peers" in schema["input_schema"]["properties"]["action"]["enum"]
	assert "action=peers" in schema["description"]
	out = await t.execute({"action": "peers"}, AbortController())
	assert out.is_error is False
	assert out.content == "(no peers)"


@pytest.mark.asyncio
async def test_subagent_cannot_mutate_memdir(env):
	tool = _tool(env)
	tool.set_agent_id("agent-sub-1")
	out = await tool.execute(
		{"action": "write", "type": "user", "content": "secret"},
		AbortController(),
	)
	assert out.is_error
	assert "sub-agents" in out.content.lower()
	wsid = workspace_id(str(env))
	assert load_notes(wsid) == []


@pytest.mark.asyncio
async def test_search_appends_pending_proposals_notice(env, monkeypatch):
	"""批次1 补偿：Proposals 下线 T_now 后，search 结果附带待审计数行。

	空命中也带计数（召回通道不依赖命中）；有命中时垫在末尾。
	"""
	import memory.instruction_maintain as im

	monkeypatch.setattr(
		im,
		"list_pending_proposals",
		lambda _wsid: [{"status": "pending"}, {"status": "pending"}],
	)
	t = _tool(env)

	# 1) 空命中：计数行取代 "(no memory hits)"
	out = await t.execute(
		{"action": "search", "query": "不存在的词条zzz"}, AbortController()
	)
	assert "另有 2 条 XEYO.md 写入提案待审" in out.content

	# 2) 有命中：计数行垫在末尾
	await t.execute(
		{"action": "write", "type": "feedback", "content": "评测偏好用中文",
		 "title": "偏好", "source_kind": "user"},
		AbortController(),
	)
	out = await t.execute(
		{"action": "search", "query": "偏好"}, AbortController()
	)
	assert out.content.strip().endswith("另有 2 条 XEYO.md 写入提案待审（/proposals 查看）。")


@pytest.mark.asyncio
async def test_search_no_proposals_keeps_legacy_shape(env, monkeypatch):
	"""无待审提案时：search 形状与旧合同一致（空命中 → no memory hits）。"""
	import memory.instruction_maintain as im

	monkeypatch.setattr(im, "list_pending_proposals", lambda _wsid: [])
	out = await _tool(env).execute(
		{"action": "search", "query": "不存在的词条zzz"}, AbortController()
	)
	assert out.content == "(no memory hits)"
