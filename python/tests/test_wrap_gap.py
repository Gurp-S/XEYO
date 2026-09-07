import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.wrap_gap import (
	build_gap_lines,
	clear_gap,
	compose_guide_text,
	compose_gap_text,
	current_gap,
	publish_gap,
)
from tools.todo_write_tool.types import TodoItem


def _item(content="a", status="completed", output="dist/out.zip"):
	return TodoItem(
		id="1", content=content, status=status, active_form="Doing", output=output
	)


# ====== build_gap_lines: 纯函数 stat 判据 ======

def test_gap_only_completed_with_output_and_missing(tmp_path):
	root = str(tmp_path)
	(tmp_path / "ok.txt").write_text("x")
	todos = [
		_item("present", output="ok.txt"),          # 在盘 → 不列
		_item("missing", output="no.txt"),          # 缺失 → 列
		_item("no-output", output=""),              # 无 output → 跳
		TodoItem("pending", "pending", "Doing", output="p.txt"),  # 未完成 → 跳
	]
	lines = build_gap_lines(todos, root)
	assert len(lines) == 1
	assert "no.txt" in lines[0] and "未落盘" in lines[0]
	assert "ok.txt" not in lines[0]


def test_gap_empty_when_nothing_missing(tmp_path):
	(tmp_path / "a.txt").write_text("x")
	assert build_gap_lines([_item(output="a.txt")], str(tmp_path)) == []
	assert build_gap_lines([], str(tmp_path)) == []
	assert build_gap_lines(None, str(tmp_path)) == []
	assert build_gap_lines([_item()], "") == []


def test_gap_max_items_limited(tmp_path):
	todos = [_item(f"m{i}", output=f"m{i}.txt") for i in range(10)]
	lines = build_gap_lines(todos, str(tmp_path))
	assert len(lines) <= 5


# ====== 模块级 publish/current ======

def test_gap_publish_consume_roundtrip():
	clear_gap()
	assert current_gap() == ""
	publish_gap("  hello  ")
	assert current_gap() == "hello"
	clear_gap()
	assert current_gap() == ""


# ====== compose text ======

def test_compose_texts():
	assert compose_gap_text([]) == ""
	g = compose_gap_text(["- x"])
	assert "x" in g and "- x" in g
	guide = compose_guide_text(3, [])
	assert "3" in guide
	guide2 = compose_guide_text(0, ["- m → p.txt(未落盘)"])
	assert "p.txt" in guide2
	assert compose_guide_text(2, ["- a"]) == compose_guide_text(2, ["- a"])
