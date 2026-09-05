"""Multi-Agent P1：瘦子 agent 提示；同轮多 Agent 可并行分区；chip 软提示可测。"""

from __future__ import annotations

import inspect

import pytest
from msgtypes.message import ToolUse
from tools.agent_tool.prompt import DESCRIPTION, MULTI_AGENT_HINT
from tools.catalog import build_default_registry
from tools.orchestration import partition_tool_calls


@pytest.mark.asyncio
async def test_p1_subagent_system_omits_xeyo_md(tmp_path):
	"""子 agent 前缀不含 XEYO.md（include_context_blocks=False）。"""
	from prompt.assembler import PromptAssembler
	from prompt.system_prompt import SUBAGENT_APPEND

	(tmp_path / "XEYO.md").write_text(
		"PROJECT RULE: always yell loudly about widgets\n" * 40,
		encoding="utf-8",
	)
	asm = PromptAssembler()
	fat, _ = await asm.build_system_parts(
		cwd=str(tmp_path),
		model="m",
		tool_names=["Read", "Grep"],
		append_system_prompt=SUBAGENT_APPEND,
		include_context_blocks=True,
	)
	slim, _ = await asm.build_system_parts(
		cwd=str(tmp_path),
		model="m",
		tool_names=["Read", "Grep"],
		append_system_prompt=SUBAGENT_APPEND,
		include_context_blocks=False,
	)
	assert "yell loudly about widgets" in fat
	assert "yell loudly about widgets" not in slim
	assert "短命子 Agent" in slim or "子 Agent" in slim
	assert len(slim) < len(fat)


def test_p1_three_agents_partition_as_one_concurrent_batch():
	"""同轮三个 Agent tool_use → 一个 concurrency-safe 批次（真并行）。"""
	reg = build_default_registry(cwd=".")
	uses = [
		ToolUse(id="1", name="Agent", input={"task_id": "a", "desc": "A"}),
		ToolUse(id="2", name="Agent", input={"task_id": "b", "desc": "B"}),
		ToolUse(id="3", name="Agent", input={"task_id": "c", "desc": "C"}),
	]
	batches = partition_tool_calls(reg, uses)
	assert len(batches) == 1
	safe, batch = batches[0]
	assert safe is True
	assert [tu.id for tu in batch] == ["1", "2", "3"]


def test_p1_agent_then_write_splits_batches():
	"""Agent（safe）后接 Write（unsafe）→ 拆成两批，写串行。"""
	reg = build_default_registry(cwd=".")
	uses = [
		ToolUse(id="1", name="Agent", input={"task_id": "a", "desc": "A"}),
		ToolUse(id="2", name="Agent", input={"task_id": "b", "desc": "B"}),
		ToolUse(
			id="3",
			name="Write",
			input={"file_path": "x.txt", "content": "hi"},
		),
	]
	batches = partition_tool_calls(reg, uses)
	assert len(batches) == 2
	assert batches[0][0] is True and len(batches[0][1]) == 2
	assert batches[1][0] is False and batches[1][1][0].name == "Write"


def test_p1_chip_hint_and_description_encourage_parallel_spawn():
	assert "同回合" in MULTI_AGENT_HINT or "并行" in MULTI_AGENT_HINT
	assert "Agent" in MULTI_AGENT_HINT
	assert "concurrently" in DESCRIPTION.lower() or "ONE turn" in DESCRIPTION
	assert "tool_result" in DESCRIPTION.lower()


def test_p1_run_subagent_passes_slim_flags():
	"""源码契约：子 agent body 必须关 context blocks + Memory index。"""
	from engine import subagent_runner

	src = inspect.getsource(subagent_runner._run_subagent_body)
	assert "include_context_blocks=False" in src
	assert "include_memory_index=False" in src
