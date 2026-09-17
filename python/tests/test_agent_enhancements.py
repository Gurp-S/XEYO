"""T14：子代理增强——净化清单 / settlement 通知 / agents/*.toml 角色文件。

- 净化清单：子代理上下文（in_subagent）不注入 peer presence、文件冲突、
  浏览器预览、repeat guard 等易变块。
- 结算通知：子代理结果未带回主会话（abort/异常）时，下一轮 T_now 注入
  source-attributed 通知，取走即清（幂等）。
- 角色文件：agents/*.toml fail-closed 加载；未知 agent_type 报错不占并发槽。
"""

from __future__ import annotations

import asyncio

import pytest

from engine.agent_roles import (
	load_agent_roles,
	role_developer_suffix,
)
from engine.agent_settlement import (
	drain_agent_settlements,
	format_settlement_block,
	pending_count,
	record_agent_settlement,
)


# ---------------------------------------------------------------------------
# 角色文件
# ---------------------------------------------------------------------------


def _write(path, text):
	path.write_text(text, encoding="utf-8")


def test_agent_roles_load_and_skip(tmp_path):
	agents = tmp_path / "agents"
	agents.mkdir()
	_write(
		agents / "reviewer.toml",
		'name = "reviewer"\ndescription = "只读代码评审"\n'
		'nickname = "评审员"\ndeveloper_instructions = "先读后评"\n',
	)
	_write(agents / "broken.toml", "name = [unclosed\n")
	_write(agents / "noname.toml", 'description = "没有 name"\n')
	# 命名保证排在 reviewer.toml 之后：同名角色 → 后者被跳过（first-wins）
	_write(agents / "zdup.toml", 'name = "reviewer"\ndescription = "重复"\n')

	roles = load_agent_roles(tmp_path)
	assert set(roles) == {"reviewer"}
	role = roles["reviewer"]
	assert role.nickname == "评审员"
	assert role.developer_instructions == "先读后评"
	assert role_developer_suffix(role).startswith("# Role: 评审员")
	assert "先读后评" in role_developer_suffix(role)
	assert role_developer_suffix(None) == ""


def test_agent_roles_missing_dir(tmp_path):
	assert load_agent_roles(tmp_path / "nope") == {}


# ---------------------------------------------------------------------------
# 结算通知
# ---------------------------------------------------------------------------


def test_settlement_record_drain_format():
	record_agent_settlement(
		"s1",
		agent_id="agent-t1-abc",
		task_id="t1",
		status="interrupted",
		summary="子代理结果未带回主会话（回合被中断或异常）",
	)
	assert pending_count("s1") == 1
	notices = drain_agent_settlements("s1")
	assert len(notices) == 1
	assert notices[0].agent_id == "agent-t1-abc"
	assert notices[0].status == "interrupted"
	# 取走即清
	assert drain_agent_settlements("s1") == []
	block = format_settlement_block(notices)
	assert "background only" in block
	assert "`agent-t1-abc`" in block
	assert "[interrupted]" in block
	assert format_settlement_block([]) == ""


def test_settlement_capped_per_session():
	for i in range(24):
		record_agent_settlement(
			"s-cap", agent_id=f"agent-x-{i}", status="interrupted"
		)
	assert pending_count("s-cap") <= 16


# ---------------------------------------------------------------------------
# 净化清单 + 结算注入（pre_llm_inject）
# ---------------------------------------------------------------------------


@pytest.fixture()
def _volatile_markers(monkeypatch):
	"""把易变块源函数替换成固定标记，便于断言出现/缺席。"""
	import engine.session_presence as sp
	import engine.repeat_guard as rg
	import prompt.pre_llm_inject as pli

	monkeypatch.setattr(sp, "peer_notice_block", lambda *a, **k: "PEERMARK")
	monkeypatch.setattr(pli, "file_conflict_block", lambda *a, **k: "CONFLICTMARK")
	monkeypatch.setattr(pli, "browser_preview_block", lambda: "PREVIEWMARK")
	monkeypatch.setattr(rg, "current_advice", lambda: "REPEATMARK")
	# 结算标记：直接预置一条真实结算
	record_agent_settlement(
		"s-inj", agent_id="agent-m-1", task_id="m1", status="interrupted",
		summary="lost result",
	)
	yield
	drain_agent_settlements("s-inj")


def _projected():
	return [{"role": "user", "content": "hi"}]


def _joined(projected) -> str:
	import json

	return json.dumps(projected, ensure_ascii=False)


def test_purify_subagent_skips_volatile_blocks(tmp_path, _volatile_markers):
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	ctx = InjectContext(
		cwd=str(tmp_path), session_id="s-inj", subagent=True
	)
	out = run_pre_llm_inject(_projected(), ctx)
	text = _joined(out)
	for mark in ("PEERMARK", "CONFLICTMARK", "PREVIEWMARK", "REPEATMARK"):
		assert mark not in text


def test_main_session_keeps_volatile_blocks(tmp_path, _volatile_markers):
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	ctx = InjectContext(
		cwd=str(tmp_path), session_id="s-inj", subagent=False
	)
	out = run_pre_llm_inject(_projected(), ctx)
	text = _joined(out)
	for mark in ("PEERMARK", "CONFLICTMARK", "PREVIEWMARK", "REPEATMARK"):
		assert mark in text


def test_settlement_block_injected_once(tmp_path, _volatile_markers):
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	ctx = InjectContext(
		cwd=str(tmp_path), session_id="s-inj", subagent=False
	)
	out = run_pre_llm_inject(_projected(), ctx)
	text = _joined(out)
	assert "子代理结算" in text
	assert "agent-m-1" in text
	# 第二轮：取走即清，不再注入
	out2 = run_pre_llm_inject(_projected(), ctx)
	assert "agent-m-1" not in _joined(out2)


# ---------------------------------------------------------------------------
# Agent 工具：agent_type
# ---------------------------------------------------------------------------


def test_agent_tool_schema_and_parse():
	from tools.agent_tool.agent_tool import AgentTool

	tool = AgentTool(cwd=".", session_id="s")
	schema = tool.schema()
	assert "agent_type" in schema["input_schema"]["properties"]
	raw = tool.parse_input(
		{"task_id": "t", "desc": "d", "agent_type": "reviewer"}
	)
	assert raw.agent_type == "reviewer"


def test_agent_tool_unknown_agent_type_no_slot_leak(tmp_path):
	from engine.abort import AbortController
	from tools.agent_tool.agent_tool import AgentTool

	tool = AgentTool(cwd=str(tmp_path), session_id="sess-x")
	inp = {"task_id": "t1", "desc": "d", "agent_type": "nope"}
	r1 = asyncio.run(tool.execute(inp, AbortController()))
	assert r1.is_error is True
	assert "unknown agent_type" in r1.content
	# 并发槽未被泄漏：第二次同样直接报错，而不是 max concurrent
	r2 = asyncio.run(tool.execute(dict(inp), AbortController()))
	assert "unknown agent_type" in r2.content
	assert "max concurrent" not in r2.content


def test_agent_role_auto_desc_and_suffix(tmp_path):
	agents = tmp_path / "agents"
	agents.mkdir()
	_write(
		agents / "tester.toml",
		'name = "tester"\ndescription = "跑测试"\n'
		'developer_instructions = "只跑相关测试"\n',
	)
	roles = load_agent_roles(tmp_path)
	role = roles["tester"]
	# desc 缺省时回退角色描述
	auto = (role.description or role.display)[:120]
	assert auto == "跑测试"
	suffix = role_developer_suffix(role)
	assert "# Role: tester" in suffix
	assert "只跑相关测试" in suffix
