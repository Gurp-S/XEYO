"""Multi-Agent P0 回归：旧流水线已删；工具轮不挂 Memory；Agent tool_result 可续写。"""

from __future__ import annotations

from engine.query_loop import _attach_turn_context, _plan_tool_schemas
from tools.agent_tool.agent_tool import _format_agent_tool_result
from tools.agent_tool.prompt import MULTI_AGENT_HINT
from tools.catalog import build_default_registry


def test_p0_chat_completions_never_calls_legacy_stream():
	from pathlib import Path

	src = (Path(__file__).resolve().parents[1] / "server" / "routers" / "chat.py").read_text(
		encoding="utf-8"
	)
	assert "async def _multi_agent_stream" not in src
	assert "def _tasks_from_raw" not in src
	assert "_multi_agent_stream(" not in src
	assert "multi_agent_retired" not in src

def test_p0_tool_round_skips_memory_index(monkeypatch):
	monkeypatch.setattr(
		"memory.runtime.memory_index_context_block",
		lambda: (
			"# Memory index (background only — NOT the user request)\n"
			"- Tool Test Result\n"
			"- 最终测试完成\n"
		),
	)
	msgs = [
		{"role": "user", "content": "测试多agent工具：创建 foo.txt"},
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": "1", "name": "Agent"}],
		},
		{
			"role": "tool",
			"content": _format_agent_tool_result(
				agent_id="agent-x",
				task_id="t1",
				desc="创建 foo.txt",
				body="Created foo.txt with hello",
				is_error=False,
			),
		},
	]
	out = _attach_turn_context(
		msgs,
		approved_plan=None,
		forced_wrap_up=False,
		runtime_notice=None,
		include_memory_index=True,
		multi_agent=True,
	)
	assert out[-1]["role"] == "user"
	parts = out[-1]["content"]
	assert isinstance(parts, list)
	# 声道无关：legacy=text 块；env_channel（方案A）=伪对 tool_result 正文
	blob = "\n".join(
		str(p.get("text") or p.get("content") or "")
		for p in parts
		if isinstance(p, dict)
	)
	assert "# Continue" in blob
	assert "Memory index" not in blob
	assert "Tool Test Result" not in blob
	assert "Multi-Agent preference" in blob or MULTI_AGENT_HINT[:40] in blob


def test_p0_user_turn_no_longer_pushes_memory_index(monkeypatch):
	"""批次3：Memory index 不再推送 T_now（能力宣告住工具 description）。"""
	monkeypatch.setattr(
		"memory.runtime.memory_index_context_block",
		lambda: "# Memory index (background only — NOT the user request)\n- note",
	)
	out = _attach_turn_context(
		[{"role": "user", "content": "普通问题"}],
		approved_plan=None,
		forced_wrap_up=False,
		runtime_notice=None,
		include_memory_index=True,
		multi_agent=False,
	)
	blob = str(out[-1].get("content"))
	assert "Memory index" not in blob


def test_p0_agent_tool_result_format_blocks_memory_hijack():
	text = _format_agent_tool_result(
		agent_id="a1",
		task_id="step1",
		desc="统计 JS 文件",
		body="Found 0 JS files",
		is_error=False,
	)
	assert "[Agent tool_result" in text
	assert "status=OK" in text
	assert "Assigned task: 统计 JS 文件" in text
	assert "Found 0 JS files" in text
	assert "ORIGINAL request" in text
	assert "Memory" in text

	err = _format_agent_tool_result(
		agent_id="a2",
		task_id="step2",
		desc="坏了",
		body="timeout",
		is_error=True,
	)
	assert "status=ERROR" in err


def test_p0_chip_off_agent_still_in_schemas():
	reg = build_default_registry(cwd=".")
	names = {str(s.get("name") or "") for s in _plan_tool_schemas(reg, reg.schemas())}
	assert "Agent" in names
