"""iLink 作答命令（#11 手机侧桥）契约测试：解析别名 + 解析挂起提问 + 回执两态。"""

from __future__ import annotations

import pytest

from channels.ilink.service import _run_command
from channels.remote_commands import parse_command
from permissions.ask_store import default_ask_store


def test_parse_command_answer_forms() -> None:
	hit = parse_command("/answer 42")
	assert hit is not None and hit.name == "answer" and hit.arg == "42"
	hit = parse_command("回答 甲选项")
	assert hit is not None and hit.name == "answer" and hit.arg == "甲选项"
	hit = parse_command("答 好")
	assert hit is not None and hit.name == "answer" and hit.arg == "好"
	# 裸词（无参）也归该命令：由 service 回用法提示，而不是落进模型。
	hit = parse_command("回答")
	assert hit is not None and hit.name == "answer" and hit.arg == ""
	# 普通文本不许被误判成命令。
	assert parse_command("随便聊聊") is None
	assert parse_command("回答是什么") is None


def _mk_pending(sid: str):
	store = default_ask_store()
	item = store.create(
		session_id=sid,
		turn_id="t1",
		question="选哪个？",
		options=["甲", "乙"],
	)
	return store, item


@pytest.mark.asyncio
async def test_run_command_answer_resolves_pending() -> None:
	sid = "ilink:test-answer"
	store, item = _mk_pending(sid)
	reply = await _run_command(
		"answer", "回答 甲", None, session_id=sid, arg="甲"  # type: ignore[arg-type]
	)
	assert reply == "已提交回答。"
	got = store.get(item.request_id)
	assert got is not None and got.resolved is True and got.answer == "甲"


@pytest.mark.asyncio
async def test_run_command_answer_without_pending() -> None:
	reply = await _run_command(
		"answer", "回答 甲", None, session_id="ilink:no-pending", arg="甲"  # type: ignore[arg-type]
	)
	assert reply == "当前没有待回答的提问"


@pytest.mark.asyncio
async def test_run_command_answer_empty_arg_is_usage() -> None:
	reply = await _run_command(
		"answer", "回答", None, session_id="ilink:x", arg=""  # type: ignore[arg-type]
	)
	assert reply is not None and reply.startswith("用法")
