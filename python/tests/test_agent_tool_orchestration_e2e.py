"""端到端：Agent 工具经 orchestration progress_q 吐出 multi_agent xy 帧。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from engine.abort import AbortController
from msgtypes.events import ToolProgressEvent
from msgtypes.message import ToolUse
from tools.agent_tool import AgentTool
from tools.base_tool import ToolResult
from tools.orchestration import run_tools_partitioned
from tools.tool_registry import ToolRegistry


@dataclass
class _FakeRR:
    conclusion: str = "done:ok"
    files_touched: list[str] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    had_write_stale: bool = False
    stop_reason: str = "finished"


@pytest.mark.asyncio
async def test_agent_tool_progress_xy_through_orchestration(monkeypatch, tmp_path):
    async def _fake_run_subagent(**kwargs: Any) -> _FakeRR:
        cb = kwargs.get("on_text_delta")
        if callable(cb):
            cb("hello-")
            cb("world")
        return _FakeRR(conclusion="sub finished", files_touched=["a.md"])

    monkeypatch.setattr(
        "engine.subagent_runner.run_subagent",
        _fake_run_subagent,
    )

    at = AgentTool(cwd=str(tmp_path), session_id="sess_tool")
    at.set_runtime_provider(
        lambda: type(
            "R",
            (),
            {
                "model_client": object(),
                "prompt_assembler": object(),
                "workspace_root": str(tmp_path),
                "append_system_prompt": "",
                "date_iso": "2026-08-29",
            },
        )()
    )
    reg = ToolRegistry(cwd=str(tmp_path))
    reg.register(at)

    q: asyncio.Queue[Any] = asyncio.Queue()
    results = await run_tools_partitioned(
        reg,
        [ToolUse(id="tu1", name="Agent", input={"task_id": "t1", "desc": "write a"})],
        AbortController(),
        progress_q=q,
    )
    assert len(results) == 1
    assert not results[0].is_error
    assert "sub finished" in results[0].content
    assert results[0].metadata and results[0].metadata.get("agent_id")

    events: list[ToolProgressEvent] = []
    while not q.empty():
        events.append(q.get_nowait())
    xy_types = [(e.xy or {}).get("type") for e in events if getattr(e, "xy", None)]
    assert "multi_agent_task" in xy_types
    assert "multi_agent_delta" in xy_types
    assert "multi_agent_progress" in xy_types
    deltas = "".join(
        (e.xy or {}).get("text", "")
        for e in events
        if (e.xy or {}).get("type") == "multi_agent_delta"
    )
    assert deltas == "hello-world"
    done = next(e for e in events if (e.xy or {}).get("type") == "multi_agent_progress")
    assert done.xy["status"] == "done"
