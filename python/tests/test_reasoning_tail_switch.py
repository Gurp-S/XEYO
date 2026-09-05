"""上一轮思考回顾注入开关：默认关（移除），显式开启恢复。

优先级：会话/请求显式设置（set_reasoning_tail_enabled，GUI 设置经 T31
模式链路）> 环境变量 XEYO_REASONING_TAIL（进程级默认）。

捕获在 query_loop 经 reasoning_tail_enabled() 门控；注入器（run_pre_llm_inject）
仍按 InjectContext.previous_reasoning_tail 渲染——门控点选在引擎捕获侧，
保证注入逻辑保持确定性（现有注入器测试不受开关影响）。
"""

from __future__ import annotations

from permissions.policy import (
	reasoning_tail_enabled,
	set_reasoning_tail_enabled,
)


def test_reasoning_tail_default_off(monkeypatch) -> None:
	set_reasoning_tail_enabled(None)
	monkeypatch.delenv("XEYO_REASONING_TAIL", raising=False)
	assert reasoning_tail_enabled() is False


def test_reasoning_tail_env_on(monkeypatch) -> None:
	set_reasoning_tail_enabled(None)
	for v in ("1", "true", "on", "ON", "True"):
		monkeypatch.setenv("XEYO_REASONING_TAIL", v)
		assert reasoning_tail_enabled() is True
	set_reasoning_tail_enabled(None)


def test_reasoning_tail_env_off_values(monkeypatch) -> None:
	set_reasoning_tail_enabled(None)
	for v in ("0", "false", "off", ""):
		monkeypatch.setenv("XEYO_REASONING_TAIL", v)
		assert reasoning_tail_enabled() is False


def test_session_setting_overrides_env(monkeypatch) -> None:
	"""显式会话/请求设置 > env 进程默认；清除后回落 env。"""
	monkeypatch.setenv("XEYO_REASONING_TAIL", "1")
	set_reasoning_tail_enabled(True)
	assert reasoning_tail_enabled() is True
	set_reasoning_tail_enabled(False)
	assert reasoning_tail_enabled() is False
	set_reasoning_tail_enabled(None)
	assert reasoning_tail_enabled() is True  # 清除显式值 → env 兜底
	set_reasoning_tail_enabled(None)


def test_query_loop_gates_reasoning_tail_capture() -> None:
	"""源码契约：捕获必须经 reasoning_tail_enabled() 门控（默认关 = 不捕获），
	且子代理（T14 净化清单）不继承。"""
	from pathlib import Path

	src = (
		Path(__file__).resolve().parents[1] / "engine" / "query_loop.py"
	).read_text(encoding="utf-8")
	assert "reasoning_tail_enabled()" in src
	assert "not in_subagent()" in src
	assert "previous_reasoning_tail = reasoning_blob[-600:]" in src
