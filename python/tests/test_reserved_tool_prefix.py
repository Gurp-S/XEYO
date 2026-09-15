"""模型发起的保留名调用必须在执行层被中性拒绝——契约，不是巧合。

背景（第六轮实录）：环境声道把易变块装进**仅存在于投影**的伪对
``assistant(xeyo_env_notice) → tool_result``。投影里长着这个形状，模型会模仿它
再发一次同名 tool_use；而该调用**确实能换回一段 ``[system-environment]`` 正文**，
于是「模型幻觉调用」在审计上被读成「引擎注入」（第五轮两次误导）。

本文件把四件事钉成契约：

1. 保留前缀常量的值与 ``prompt.t_now_strategy.ENV_ID_PREFIX`` **同源**（不得漂移）；
2. ``ToolRegistry.run`` 对模型发起的保留名**中性拒绝**，且拒绝发生在注册表查询
   **之前**（即使有人真把工具注册成这个名字，也走不到它）；
3. 该名字**永不进** ``schemas()``（tools 数组会话内冻结红线）；
4. 引擎自身的 env 投影**照常构造**——拒绝规则不得误伤它。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msgtypes.message import ToolUse  # noqa: E402
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject  # noqa: E402
from prompt.t_now_strategy import (  # noqa: E402
	ENV_ID_PREFIX,
	ENV_TOOL_NAME,
	set_t_now_strategy,
)
from tools.tool_registry import RESERVED_TOOL_PREFIX, ToolRegistry  # noqa: E402


def test_reserved_prefix_is_same_source_as_env_channel_prefix():
	assert RESERVED_TOOL_PREFIX == ENV_ID_PREFIX == "xeyo_env_"
	assert ENV_TOOL_NAME.startswith(RESERVED_TOOL_PREFIX)


def test_run_rejects_reserved_name_before_registry_lookup():
	reg = ToolRegistry()
	sentinel = object()
	# 故意把工具注册成保留名：拒绝必须发生在查询之前，否则模型就拿到了
	# 一个「自造注入通道」。
	reg._tools[ENV_TOOL_NAME] = sentinel  # type: ignore[assignment]
	res = asyncio.run(
		reg.run(ToolUse(id="call_reserved", name=ENV_TOOL_NAME, input={}), None)
	)
	assert res.is_error is True
	assert res.content == f"reserved environment channel: {ENV_TOOL_NAME}"
	assert "unknown tool" not in res.content
	# 中性措辞：只陈述结果，不含劝导/评价词
	for word in ("不要", "必须", "请", "should", "must", "warning"):
		assert word not in res.content
	assert reg._tools[ENV_TOOL_NAME] is sentinel, "拒绝路径不得触碰注册项"


def test_reserved_name_never_enters_schemas():
	reg = ToolRegistry()
	assert ENV_TOOL_NAME not in str(reg.schemas())
	assert ENV_TOOL_NAME not in reg._tools


def test_engine_env_projection_still_constructs():
	"""拒绝规则不得误伤引擎自己：伪对照常在注入点构造（从不经过执行层）。"""
	set_t_now_strategy(None)
	out = run_pre_llm_inject(
		[{"role": "user", "content": "task"}], InjectContext(cwd="", forced_wrap_up=True)
	)
	assert out[-2]["role"] == "assistant"
	assert out[-1]["role"] == "user"
	use = out[-2]["content"][0]
	assert use["type"] == "tool_use" and use["name"] == ENV_TOOL_NAME
	assert out[-1]["content"][0]["type"] == "tool_result"
	assert out[0]["content"] == "task", "用户消息不得被改写"
