"""侧聊（side）只读模式：复用主 agent 链路 + 一个 side 开关。

回归点：
- schema/执行两道 gate 都按只读白名单放行（含真实 registry 实例）；
- agent_mode=agent 时 side 开关依然生效（side 与 agent_mode 正交）；
- system prompt 左段在 side 模式不注入 CWD / XEYO.md instructions。
"""

from __future__ import annotations

import asyncio

from permissions.policy import (
	readonly_gate,
	set_agent_mode,
	set_side_mode,
	side_mode,
	tool_allowed_in_mode,
)
from tools.catalog import build_default_registry


def test_side_mode_allows_only_readonly_tools() -> None:
	set_side_mode(True)
	try:
		assert side_mode() is True
		assert tool_allowed_in_mode("Read")
		assert tool_allowed_in_mode("Glob")
		assert tool_allowed_in_mode("Grep")
		assert tool_allowed_in_mode("getTime")
		assert not tool_allowed_in_mode("Write")
		assert not tool_allowed_in_mode("Edit")
		assert not tool_allowed_in_mode("Bash")
		assert not tool_allowed_in_mode("TodoWrite")
		assert not tool_allowed_in_mode("Agent")
		assert not tool_allowed_in_mode("WebFetch")
		# 执行期 gate：写工具硬拒，读工具放行
		assert readonly_gate("Write") == "readonly_mode_deny"
		assert readonly_gate("Read") is None
		# agent_mode=agent（默认）下 side 依然收紧行动
		set_agent_mode("agent")
		assert readonly_gate("Edit") == "readonly_mode_deny"
	finally:
		set_side_mode(False)
	assert side_mode() is False
	# 关闭后 agent 模式恢复全量放行
	assert tool_allowed_in_mode("Write") is True


def test_side_mode_schema_filter_with_registry() -> None:
	set_side_mode(True)
	try:
		reg = build_default_registry(cwd=".")
		schemas = reg.schemas()
		names = {str(s.get("name") or "") for s in schemas}
		assert names, "registry 应产出 schema"
		allowed = {
			str(s.get("name") or "")
			for s in schemas
			if tool_allowed_in_mode(
				str(s.get("name") or ""),
				tool=reg.get(str(s.get("name") or "")),
			)
		}
		assert "Read" in allowed
		assert "Grep" in allowed
		assert not (allowed & {"Write", "Edit", "Bash", "Agent", "NotebookEdit"})
	finally:
		set_side_mode(False)


def test_side_mode_system_prompt_skips_workspace() -> None:
	from prompt.system_prompt import fetch_system_prompt_parts

	set_side_mode(True)
	try:
		parts = asyncio.run(
			fetch_system_prompt_parts(cwd=".", model="m", tool_names=[])
		)
		text = "\n".join(parts.default_system_prompt)
		assert "CWD:" not in text
		assert parts.user_context == {}
	finally:
		set_side_mode(False)

	parts = asyncio.run(fetch_system_prompt_parts(cwd=".", model="m", tool_names=[]))
	assert any("CWD:" in seg for seg in parts.default_system_prompt)
	assert "instructions" in parts.user_context
