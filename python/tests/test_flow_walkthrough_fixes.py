"""Flow-walkthrough contract fixes: headless ASK deny + stop_requested carry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from permissions.policy import set_agent_mode, set_permission_mode
from permissions.workspace_policy import clear_policy_cache
from tools.catalog import build_subagent_registry
from tools.fileio.read_state import ReadFileState


def test_subagent_write_always_mode_denies_without_coordinator(tmp_path):
	"""无 coordinator 时 ASK 一律 DENY（不再静默放行）。"""
	set_agent_mode("agent")
	set_permission_mode("always")
	reg = build_subagent_registry(
		cwd=str(tmp_path),
		tool_names=["Read", "Write", "Edit"],
		read_state=ReadFileState(),
		agent_id="agent-x",
	)
	target = str(tmp_path / "n.ts")
	tu = ToolUse(id="u1", name="Write", input={"file_path": target, "content": "hi\n"})
	res = asyncio.run(reg.run(tu, AbortController(), coordinator=None))
	assert res.is_error
	assert "no resolver" in (res.content or "").lower() or "permission" in (
		res.content or ""
	).lower()
	assert not Path(target).exists()


def test_subagent_write_risk_mode_allows_safe_without_coordinator(tmp_path):
	"""risk 模式安全写为 ALLOW，无 coordinator 仍可执行。

	注意：默认仓库策略为 write=ask（workspace_policy 缺省），会把 risk 模式收紧成
	always（每写必 ASK）→ 无 coordinator 即报 no resolver。本用例显式放宽松仓库
	策略 write=allow，使 risk 模式的安全写自动放行——这才是「risk 模式允许写」
	语义成立的前提。
	"""
	(tmp_path / ".xeyo-policy.json").write_text(
		json.dumps({"write": "allow"}), encoding="utf-8"
	)
	clear_policy_cache()
	set_agent_mode("agent")
	set_permission_mode("risk")
	reg = build_subagent_registry(
		cwd=str(tmp_path),
		tool_names=["Read", "Write", "Edit"],
		read_state=ReadFileState(),
		agent_id="agent-x",
	)
	target = str(tmp_path / "n.ts")
	tu = ToolUse(id="u1", name="Write", input={"file_path": target, "content": "hi\n"})
	res = asyncio.run(reg.run(tu, AbortController(), coordinator=None))
	assert not res.is_error, res.content
	assert Path(target).read_text(encoding="utf-8") == "hi\n"


@pytest.mark.asyncio
async def test_submit_honors_stop_requested_option():
	from engine.query_engine import build_default_engine
	from msgtypes.events import StoppedEvent

	eng = build_default_engine(model_backend="fake")
	events = []
	async for ev in eng.submit("hello", options={"stop_requested": True}):
		events.append(ev)
	assert eng.abort_controller.aborted
	assert any(isinstance(e, StoppedEvent) and e.reason == "aborted" for e in events)
