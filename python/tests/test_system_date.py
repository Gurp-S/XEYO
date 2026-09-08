"""左段不含 Date：避免跨日/固化日期污染 KV；时刻走 getTime。"""

from __future__ import annotations

import asyncio
from datetime import date


from prompt.assembler import PromptAssembler
from prompt.system_prompt import assemble_system_prompt, fetch_system_prompt_parts

FIXED = "2026-08-18"


def test_left_has_no_date_even_when_date_iso_passed(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()

	async def _run() -> str:
		parts = await fetch_system_prompt_parts(
			cwd=str(root),
			model="deepseek",
			tool_names=["getTime"],
			date_iso=FIXED,
		)
		return assemble_system_prompt(parts, include_context_blocks=True)

	text = asyncio.run(_run())
	assert f"Date: {FIXED}" not in text
	assert "Date:" not in text
	assert f"CWD: {root}" in text
	# A1 裁决：TOOL_POLICY 已从左段删除——任何工具纪律文本不再出现。
	assert "getTime" not in text


def test_left_has_no_today_date(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()

	async def _run() -> str:
		parts = await fetch_system_prompt_parts(
			cwd=str(root),
			model="deepseek",
			tool_names=[],
		)
		return assemble_system_prompt(parts, include_context_blocks=True)

	text = asyncio.run(_run())
	assert f"Date: {date.today().isoformat()}" not in text
	assert "Date:" not in text


def test_assembler_accepts_date_iso_without_injecting(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	root = tmp_path / "proj"
	root.mkdir()

	async def _run() -> str:
		return await PromptAssembler().build_system(
			cwd=str(root),
			model="deepseek",
			tool_names=["getTime"],
			date_iso=FIXED,
		)

	text = asyncio.run(_run())
	assert "Date:" not in text
	assert f"CWD: {root}" in text


def test_engine_still_freezes_date_iso_for_callers(tmp_path):
	"""兼容：引擎仍固化 date_iso 并传给 assembler（正文不再使用）。"""
	from engine.query_engine import QueryEngine
	from model.chunks import ModelChunk
	from tools.echo import EchoTool
	from tools.tool_registry import ToolRegistry

	class FakeAssembler:
		def __init__(self) -> None:
			self.kwargs: dict | None = None

		async def build_system(self, **kw) -> str:
			self.kwargs = dict(kw)
			return "SYSTEM"

		def build(self, system: str, history: list[dict]) -> list[dict]:
			return [{"role": "system", "content": system}, *history]

	class SilentModel:
		async def stream(self, messages, tools, abort):
			abort.raise_if_aborted()
			yield ModelChunk(kind="text_delta", text="ok")

	reg = ToolRegistry()
	reg.register(EchoTool())
	asm = FakeAssembler()
	eng = QueryEngine(
		{
			"cwd": str(tmp_path),
			"tools": reg,
			"model_client": SilentModel(),  # type: ignore[typeddict-item]
			"prompt_assembler": asm,
			"max_turns": 2,
		}
	)
	assert eng._date_iso == date.today().isoformat()

	async def _submit() -> None:
		async for _ in eng.submit_message("hi"):
			pass

	asyncio.run(_submit())
	assert asm.kwargs is not None
	assert asm.kwargs["date_iso"] == eng._date_iso
