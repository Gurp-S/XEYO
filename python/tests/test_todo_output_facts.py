"""TodoWrite 产物核对尾注的离线测试（#9，用户裁决 2026-09-08）。

背景：R4 的 ``_materialization_facts`` 已在每次 TodoWrite 后对
completed+output 条目 stat 磁盘。本文件锁死两条契约：
1. **纯信息传递**——尾注只陈述情况，绝不含命令/劝说/引导措辞；
2. 事实准确性——非路径 output（URL 等）不报"未落盘"，fail-open。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController  # noqa: E402
from tools.todo_write_tool.todo_write_tool import TodoWriteTool  # noqa: E402
from tools.todo_write_tool.types import TodoItem  # noqa: E402

#: 引导/命令/劝说类措辞黑名单——出现任意一个即违反「纯信息传递」裁决。
_PERSUASION_MARKERS = (
	"请", "应该", "建议", "务必", "优先", "记得", "需要写入", "尽快",
	"补齐", "立即", "别忘了", "需先",
)


def _item(content: str, status: str, output: str = "") -> TodoItem:
	return TodoItem(
		id=f"id-{abs(hash(content)) % 10000}",
		content=content,
		status=status,  # type: ignore[arg-type]
		active_form=f"doing {content}",
		output=output,
	)


async def _run(tmp_path: Path, todos: list[TodoItem]) -> str:
	tool = TodoWriteTool(cwd=str(tmp_path))
	result = await tool.execute({"todos": [t.to_dict() for t in todos]}, AbortController())
	assert result.is_error is not True
	return result.content


class TestMaterializationFacts:
	def test_missing_output_is_factual_only(self, tmp_path):
		content = asyncio.run(
			_run(tmp_path, [_item("写报告", "completed", output="reports/summary.md")])
		)
		assert "[引擎核对]" in content
		assert "reports/summary.md" in content
		assert "磁盘上不存在" in content
		low = content.lower()
		for marker in _PERSUASION_MARKERS:
			assert marker not in content, f"尾注含引导措辞: {marker}"
			assert marker not in low

	def test_existing_output_reports_size(self, tmp_path):
		target = tmp_path / "out.txt"
		target.write_text("hello", encoding="utf-8")
		content = asyncio.run(
			_run(tmp_path, [_item("写文件", "completed", output="out.txt")])
		)
		assert "[引擎核对]" in content
		assert "out.txt" in content and "已存在" in content and "5 B" in content

	def test_url_output_skipped(self, tmp_path):
		content = asyncio.run(
			_run(tmp_path, [_item("传数据", "completed", output="https://cdn.example.com/x.json")])
		)
		assert "引擎核对" not in content  # 非磁盘路径不报"未落盘"

	def test_non_completed_and_empty_output_silent(self, tmp_path):
		content = asyncio.run(
			_run(
				tmp_path,
				[
					_item("进行中", "in_progress", output="reports/a.md"),
					_item("已完成无产物", "completed"),
				],
			)
		)
		assert "引擎核对" not in content

	def test_no_leading_narrative_in_missing_row(self, tmp_path):
		"""缺失行只陈述事实，不带"该步骤标了…但…"式叙述。"""
		content = asyncio.run(
			_run(tmp_path, [_item("生成", "completed", output="missing.bin")])
		)
		row = next(line for line in content.splitlines() if "引擎核对" in line)
		assert row == "[引擎核对] 产物 missing.bin: 磁盘上不存在（该项已标 completed）"
