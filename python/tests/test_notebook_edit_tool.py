"""NotebookEdit cell-level editing + Edit/Write reject .ipynb."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.abort import AbortController
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.file_edit_tool.file_edit_tool import FileEditTool
from tools.file_write_tool.file_write_tool import FileWriteTool
from tools.fileio.read_state import ReadFileState
from tools.notebook_edit_tool import NotebookEditTool
from tools.notebook_edit_tool.prompt import IPYNB_REJECT


def _nb(*sources: str) -> dict:
	cells = []
	for s in sources:
		cells.append(
			{
				"cell_type": "code",
				"metadata": {},
				"source": [s] if not s.endswith("\n") else [s],
				"outputs": [{"output_type": "stream", "text": ["old"]}],
				"execution_count": 1,
			}
		)
	return {
		"nbformat": 4,
		"nbformat_minor": 5,
		"metadata": {},
		"cells": cells,
	}


@pytest.mark.asyncio
async def test_notebook_replace_insert_delete(tmp_path: Path) -> None:
	path = tmp_path / "n.ipynb"
	path.write_text(json.dumps(_nb("a = 1\n", "b = 2\n")), encoding="utf-8")
	state = ReadFileState()
	# 先 Read（登记 read_state）
	from tools.file_read_tool.file_read_tool import FileReadTool

	reader = FileReadTool(cwd=str(tmp_path), read_state=state)
	rr = await reader.execute({"file_path": str(path)}, AbortController())
	assert not rr.is_error
	assert "[0]" in rr.content and "code" in rr.content

	tool = NotebookEditTool(cwd=str(tmp_path))
	tool.set_read_file_state(state)

	r = await tool.execute(
		{
			"notebook_path": str(path),
			"edit_mode": "replace",
			"cell_idx": 0,
			"new_source": "a = 99\n",
		},
		AbortController(),
	)
	assert not r.is_error
	data = json.loads(path.read_text(encoding="utf-8"))
	src0 = "".join(data["cells"][0]["source"])
	assert "99" in src0
	assert data["cells"][0]["outputs"] == []
	assert data["cells"][0]["execution_count"] is None

	ins = await tool.execute(
		{
			"notebook_path": str(path),
			"edit_mode": "insert",
			"cell_idx": 1,
			"cell_type": "markdown",
			"new_source": "# hi",
		},
		AbortController(),
	)
	assert not ins.is_error
	data = json.loads(path.read_text(encoding="utf-8"))
	assert len(data["cells"]) == 3
	assert data["cells"][1]["cell_type"] == "markdown"

	dele = await tool.execute(
		{
			"notebook_path": str(path),
			"edit_mode": "delete",
			"cell_idx": 1,
		},
		AbortController(),
	)
	assert not dele.is_error
	data = json.loads(path.read_text(encoding="utf-8"))
	assert len(data["cells"]) == 2


@pytest.mark.asyncio
async def test_notebook_insert_defaults_cell_type(tmp_path: Path) -> None:
	path = tmp_path / "n.ipynb"
	path.write_text(json.dumps(_nb("x")), encoding="utf-8")
	state = ReadFileState()
	from tools.file_read_tool.file_read_tool import FileReadTool

	reader = FileReadTool(cwd=str(tmp_path), read_state=state)
	await reader.execute({"file_path": str(path)}, AbortController())
	tool = NotebookEditTool(cwd=str(tmp_path))
	tool.set_read_file_state(state)
	r = await tool.execute(
		{
			"notebook_path": str(path),
			"edit_mode": "insert",
			"new_source": "print(1)",
		},
		AbortController(),
	)
	assert not r.is_error
	assert "cells_now=2" in r.content
	data = json.loads(path.read_text(encoding="utf-8"))
	assert len(data["cells"]) == 2
	assert data["cells"][1]["cell_type"] == "code"


@pytest.mark.asyncio
async def test_notebook_requires_read_first(tmp_path: Path) -> None:
	path = tmp_path / "n.ipynb"
	path.write_text(json.dumps(_nb("x")), encoding="utf-8")
	tool = NotebookEditTool(cwd=str(tmp_path))
	r = await tool.execute(
		{
			"notebook_path": str(path),
			"edit_mode": "replace",
			"cell_idx": 0,
			"new_source": "y",
		},
		AbortController(),
	)
	assert r.is_error
	assert "read" in r.content.lower()


@pytest.mark.asyncio
async def test_notebook_out_of_range(tmp_path: Path) -> None:
	path = tmp_path / "n.ipynb"
	path.write_text(json.dumps(_nb("x")), encoding="utf-8")
	state = ReadFileState()
	from tools.file_read_tool.file_read_tool import FileReadTool

	reader = FileReadTool(cwd=str(tmp_path), read_state=state)
	await reader.execute({"file_path": str(path)}, AbortController())
	tool = NotebookEditTool(cwd=str(tmp_path))
	tool.set_read_file_state(state)
	r = await tool.execute(
		{
			"notebook_path": str(path),
			"edit_mode": "replace",
			"cell_idx": 9,
			"new_source": "y",
		},
		AbortController(),
	)
	assert r.is_error
	assert "out of range" in r.content.lower()


@pytest.mark.asyncio
async def test_edit_write_reject_ipynb(tmp_path: Path) -> None:
	path = tmp_path / "n.ipynb"
	path.write_text(json.dumps(_nb("x")), encoding="utf-8")
	state = ReadFileState()
	editor = FileEditTool(cwd=str(tmp_path), read_state=state)
	e = await editor.execute(
		{
			"file_path": str(path),
			"old_string": "x",
			"new_string": "y",
		},
		AbortController(),
	)
	assert e.is_error
	assert "NotebookEdit" in e.content
	assert IPYNB_REJECT[:20] in e.content or "NotebookEdit" in e.content

	writer = FileWriteTool(cwd=str(tmp_path))
	writer.set_read_file_state(state)
	w = await writer.execute(
		{"file_path": str(path), "content": "{}"},
		AbortController(),
	)
	assert w.is_error
	assert "NotebookEdit" in w.content


@pytest.mark.asyncio
async def test_notebook_outside_denied(tmp_path: Path) -> None:
	outside = tmp_path.parent / "out.ipynb"
	tool = NotebookEditTool(cwd=str(tmp_path))
	r = await tool.execute(
		{
			"notebook_path": str(outside),
			"edit_mode": "insert",
			"cell_type": "code",
			"new_source": "1",
		},
		AbortController(),
	)
	assert r.is_error
	assert "permission" in r.content.lower()


def test_notebook_path_picked_by_policy(tmp_path: Path) -> None:
	inside = str(tmp_path / "n.ipynb")
	d = evaluate_policy(
		"NotebookEdit",
		{
			"notebook_path": inside,
			"edit_mode": "insert",
			"cell_type": "code",
			"new_source": "1",
		},
		cwd=str(tmp_path),
	)
	assert d.decision == PermissionDecision.ALLOW
	outside = str(tmp_path.parent / "x.ipynb")
	d2 = evaluate_policy(
		"NotebookEdit",
		{"notebook_path": outside, "edit_mode": "delete", "cell_idx": 0},
		cwd=str(tmp_path),
	)
	assert d2.decision == PermissionDecision.DENY
