"""`xeyo chat` REPL：一轮抛异常不许把整个会话连根拔掉。

一次性路径（--print / 脚本）已明确把「本轮直接抛异常」当已知场景处理
（捕获 → ✗ turn failed → 返回 1）；交互 REPL 此前没有这层围栏：引擎 / 渲染层
任何非 KeyboardInterrupt 异常都会穿出 chat_async，REPL 直接掉回 shell，
用户丢掉整个会话环境。本测试钉住：坏轮之后下一行照常处理、EOF 正常收尾。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli.chat_cmd as chat_cmd


def _scripted_reader(lines: list[str]):
	it = iter(lines)

	def read(mode: str) -> str:
		try:
			return next(it)
		except StopIteration:
			raise EOFError()

	return read


@pytest.mark.asyncio
async def test_repl_survives_turn_exception(monkeypatch):
	turns: list[str] = []

	async def fake_run_turn(engine, text, **kwargs):
		turns.append(text)
		if text == "boom":
			raise RuntimeError("engine blew up")

	monkeypatch.setattr(chat_cmd, "ensure_utf8_stdio", lambda: None)
	monkeypatch.setattr(chat_cmd, "resolve_cwd", lambda cwd, persist=True: cwd or ".")
	monkeypatch.setattr(
		chat_cmd,
		"build_chat_engine",
		lambda **kw: (SimpleNamespace(session_id="sess-repl", _model_name="m"), 0),
	)
	monkeypatch.setattr(chat_cmd, "run_turn", fake_run_turn)
	monkeypatch.setattr(
		chat_cmd, "_read_repl_line", _scripted_reader(["boom", "hello", ""])
	)

	code = await asyncio.wait_for(
		chat_cmd.chat_async(
			prompt=None,
			cwd=".",
			session_id="sess-repl",
			provider="fake",
			model="",
			api_key="",
			base_url="",
			permission_mode="risk",
			agent_mode="agent",
			print_mode=False,
			json_mode=True,
		),
		timeout=5.0,
	)

	# 异常后 REPL 必须还活着：下一行照常处理，正常 EOF 收尾。
	assert code == 0
	assert turns == ["boom", "hello"]
