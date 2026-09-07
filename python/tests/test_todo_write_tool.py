"""TodoWrite 结构化输出契约：SSE 可直接消费，不再只靠交互文本反解析。"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from tools.todo_write_tool.store import TodoStore
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


@pytest.mark.asyncio
async def test_execute_emits_structured_todos() -> None:
	tool = TodoWriteTool()
	abort = AbortController()
	res = await tool.execute(
		{
			"todos": [
				{
					"content": "Run tests",
					"status": "in_progress",
					"activeForm": "Running tests",
				}
			]
		},
		abort,
	)
	assert res.is_error is False
	assert res.todos is not None
	assert res.todos[0]["status"] == "in_progress"
	assert "activeForm" in res.todos[0]
	# 模型仍能看到人类文本 + <todo_list> 标签，但 UI 无需再反解析。
	assert "<todo_list>" in res.content


@pytest.mark.asyncio
async def test_execute_empty_todos_emits_empty() -> None:
	tool = TodoWriteTool()
	abort = AbortController()
	res = await tool.execute({"todos": []}, abort)
	assert res.is_error is False
	assert res.todos == []
	assert "empty" in res.content.lower()


@pytest.mark.asyncio
async def test_execute_keeps_optional_output_field() -> None:
	"""R4 注册表：步骤产物路径作为可选结构字段贯通工具结果与 UI 载荷。"""
	tool = TodoWriteTool()
	abort = AbortController()
	res = await tool.execute(
		{
			"todos": [
				{
					"content": "Generate summary report",
					"status": "in_progress",
					"activeForm": "Generating summary report",
					"output": "reports/summary.md",
				},
				{
					"content": "Research approach",
					"status": "pending",
					"activeForm": "Researching approach",
				},
			]
		},
		abort,
	)
	assert res.is_error is False
	assert res.todos is not None
	by_content = {t["content"]: t for t in res.todos}
	assert by_content["Generate summary report"]["output"] == "reports/summary.md"
	# 未声明产物的步骤保持空串（可选语义），且老字段不变。
	assert by_content["Research approach"]["output"] == ""
	assert set(by_content["Research approach"]) >= {
		"id",
		"content",
		"status",
		"activeForm",
	}


@pytest.mark.asyncio
async def test_execute_output_survives_store_roundtrip() -> None:
	"""execute → store → to_dict：output 进 sidecar 序列化链。"""
	store = TodoStore()
	tool = TodoWriteTool(store=store)
	await tool.execute(
		{
			"todos": [
				{
					"content": "Ship artifact",
					"status": "in_progress",
					"activeForm": "Shipping artifact",
					"output": "dist/build.zip",
				}
			]
		},
		AbortController(),
	)
	stored = store.get()
	assert len(stored) == 1
	assert stored[0].output == "dist/build.zip"
	assert stored[0].to_dict()["output"] == "dist/build.zip"


@pytest.mark.asyncio
async def test_materialization_fact_reports_missing_output(tmp_path) -> None:
	"""completed + 声明产物但磁盘缺失 → 追加缺失事实（非闸门、只陈述）。"""
	tool = TodoWriteTool(cwd=str(tmp_path))
	res = await tool.execute(
		{
			"todos": [
				{
					"content": "Produce final file",
					"status": "completed",
					"activeForm": "Producing final file",
					"output": "out/result.json",
				}
			]
		},
		AbortController(),
	)
	assert res.is_error is False
	assert "[task-check]" in res.content
	assert "不存在" in res.content
	assert "out/result.json" in res.content


@pytest.mark.asyncio
async def test_materialization_fact_confirms_existing_output(tmp_path) -> None:
	"""completed + 产物已落盘 → 追加已存在事实（含字节数）。"""
	(target := tmp_path / "built").mkdir()
	(target / "app.bin").write_bytes(b"\x00" * 12)
	tool = TodoWriteTool(cwd=str(tmp_path))
	res = await tool.execute(
		{
			"todos": [
				{
					"content": "Produce final file",
					"status": "completed",
					"activeForm": "Producing final file",
					"output": "built/app.bin",
				}
			]
		},
		AbortController(),
	)
	assert res.is_error is False
	assert "[task-check]" in res.content
	assert "已存在" in res.content


@pytest.mark.asyncio
async def test_materialization_fact_skips_inprogress_and_no_output(tmp_path) -> None:
	"""in_progress 与未声明产物的条目不触发核对（零开销）。"""
	tool = TodoWriteTool(cwd=str(tmp_path))
	res = await tool.execute(
		{
			"todos": [
				{
					"content": "Research",
					"status": "in_progress",
					"activeForm": "Researching",
				},
				{
					"content": "Write up",
					"status": "pending",
					"activeForm": "Writing up",
					"output": "notes.md",
				},
			]
		},
		AbortController(),
	)
	assert res.is_error is False
	assert "[task-check]" not in res.content
