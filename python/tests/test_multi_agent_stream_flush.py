"""P0：旧 batch 流水线已删除；HTTP 仅走主循环 + Agent 工具。"""

from __future__ import annotations

from pathlib import Path


def _chat_py_text() -> str:
	return (Path(__file__).resolve().parents[1] / "server" / "routers" / "chat.py").read_text(
		encoding="utf-8"
	)


def test_legacy_multi_agent_stream_removed():
	src = _chat_py_text()
	assert "async def _multi_agent_stream" not in src
	assert "def _tasks_from_raw" not in src


def test_chat_completions_never_calls_legacy_stream():
	src = _chat_py_text()
	# 产品入口不再引用旧 batch 生成器
	assert "_multi_agent_stream(" not in src
	assert "multi_agent_retired" not in src
