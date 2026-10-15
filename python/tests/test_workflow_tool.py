"""Workflow 工具契约测试：脚本守卫 + 编排原语 + 结果形状。

不需要真模型/真子代理：``_build_agent_tool`` 被替换成脚本化的假 AgentTool，
验证的是「脚本 → 原语 → tool_result」这条链本身。
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from tools.workflow_tool.script_guard import (
    ENTRY_NAME,
    ScriptRejected,
    prepare_script,
)
from tools.workflow_tool.workflow_tool import WorkflowTool


class _FakeAgentTool:
    """假 AgentTool：按 desc 里的关键字返回固定正文，并记录调用。"""

    def __init__(self, *, fail_on: str = "") -> None:
        self.calls: list[dict] = []
        self._fail_on = fail_on

    async def execute(self, tool_input, abort):
        from tools.base_tool import ToolResult
        from tools.agent_tool.agent_tool import _format_agent_tool_result

        self.calls.append(dict(tool_input))
        desc = str(tool_input.get("desc") or "")
        is_error = bool(self._fail_on) and self._fail_on in desc
        body = "child failed" if is_error else f"result:{desc.splitlines()[0][:40]}"
        return ToolResult(
            content=_format_agent_tool_result(
                agent_id="agent-x",
                task_id=str(tool_input.get("task_id") or ""),
                desc=desc,
                body=body,
                is_error=is_error,
            ),
            is_error=is_error,
        )


def _run(script, *, meta=None, args=None, fake=None, **kwargs):
    tool = WorkflowTool(cwd=".")
    fake = fake or _FakeAgentTool()
    tool._build_agent_tool = lambda: fake  # type: ignore[assignment]
    payload = {
        "script": script,
        "meta": meta or {"name": "w", "description": "d"},
    }
    if args is not None:
        payload["args"] = args
    payload.update(kwargs)
    result = asyncio.run(tool.execute(payload, AbortController()))
    return result, fake


# ---- 静态守卫 ---------------------------------------------------------------

def test_guard_accepts_trailing_expression_and_return():
    """两种取结果写法都认：末行表达式、显式 return（顶层 return 由入口函数承接）。"""
    assert prepare_script("1 + 1").entry == ENTRY_NAME
    prepared = prepare_script("return 1")
    namespace: dict = {"__builtins__": {}}
    exec(prepared.code, namespace)
    assert namespace[prepared.entry]() == 1


@pytest.mark.parametrize(
    "bad",
    [
        "import os",
        "from os import path",
        "open('/etc/passwd')",
        "x.__class__",
        "().__class__.__bases__",
        "eval('1')",
        "exec('x=1')",
        "__builtins__",
        "globals()",
        "getattr(x, 'y')",
        "class A: pass",
        "with open('x') as f: pass",
        "lambda: __import__('os')",
    ],
)
def test_guard_rejects_escapes(bad):
    with pytest.raises(ScriptRejected):
        prepare_script(bad)


def test_guard_rejects_unknown_call():
    with pytest.raises(ScriptRejected) as exc:
        prepare_script("os_system('ls')")
    assert "not callable" in str(exc.value)


def test_guard_caps_size():
    with pytest.raises(ScriptRejected):
        prepare_script("x = 1\n" * 10_000)


def test_entry_name_is_generated_not_user_visible():
    prepared = prepare_script("agent('x')")
    assert prepared.entry == ENTRY_NAME
    with pytest.raises(ScriptRejected):
        prepare_script(f"{ENTRY_NAME}()")


# ---- 编排原语 ---------------------------------------------------------------

def test_agent_returns_child_text():
    result, fake = _run("a = agent('do the thing')\n{'got': a}")
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["agents_started"] == 1
    assert payload["value"]["got"].startswith("result:do the thing")
    assert fake.calls[0]["task_id"].startswith("wf-")


def test_agent_schema_parses_json():
    fake = _FakeAgentTool()
    # 子代理正文固定为 "result:..."，非 JSON ⇒ schema 校验失败返回 None
    result, _ = _run("v = agent('x', schema={'type': 'object'})\n{'v': v}", fake=fake)
    payload = json.loads(result.content)
    assert payload["value"]["v"] is None
    assert "not schema-valid JSON" in " ".join(payload["logs"])


def test_agent_failure_returns_none_not_fatal():
    result, _ = _run(
        "a = agent('boom')\n{'a': a}", fake=_FakeAgentTool(fail_on="boom")
    )
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["value"]["a"] is None


def test_parallel_runs_all_and_keeps_order():
    result, fake = _run(
        "r = parallel([lambda: agent('one'), lambda: agent('two')])\n{'n': len(r), 'r': r}"
    )
    payload = json.loads(result.content)
    assert payload["agents_started"] == 2
    assert payload["value"]["n"] == 2
    assert payload["value"]["r"][0].startswith("result:one")
    assert len(fake.calls) == 2


def test_pipeline_chains_stages():
    result, _ = _run(
        "r = pipeline(['a'], lambda prev, item: item + '!')\n{'r': r}"
    )
    payload = json.loads(result.content)
    assert payload["value"]["r"] == ["a!"]


def test_phase_and_log_go_to_metadata_not_body():
    result, _ = _run("phase('scan')\nlog('hello')\n{'done': True}")
    payload = json.loads(result.content)
    # 正文 = 脚本返回值，不含 phase/log 自述
    assert set(payload) == {"ok", "value", "agents_started", "phases", "logs"}
    assert payload["value"] == {"done": True}
    assert payload["phases"] == ["scan"]
    assert payload["logs"] == ["hello"]
    assert result.metadata["phases"] == ["scan"]


def test_unknown_agent_option_is_fatal():
    result, _ = _run("agent('x', isolation='worktree')")
    assert result.is_error
    payload = json.loads(result.content)
    assert payload["ok"] is False
    assert "unknown option" in payload["error"]


def test_max_agents_budget_is_enforced():
    result, _ = _run(
        "for i in range(5):\n    agent(str(i))", max_agents=2
    )
    assert result.is_error
    payload = json.loads(result.content)
    assert payload["agents_started"] == 2
    assert "budget exhausted" in payload["error"]


def test_meta_requires_name_and_description():
    tool = WorkflowTool(cwd=".")
    tool._build_agent_tool = lambda: _FakeAgentTool()  # type: ignore[assignment]
    result = asyncio.run(
        tool.execute(
            {"script": "1", "meta": {"name": "x"}}, AbortController()
        )
    )
    assert result.is_error
    assert "description" in result.content


def test_rejected_script_is_neutral_error():
    result, _ = _run("import os")
    assert result.is_error
    assert result.content.startswith("script rejected:")


def test_missing_runtime_is_reported():
    tool = WorkflowTool(cwd=".")
    result = asyncio.run(
        tool.execute(
            {"script": "1", "meta": {"name": "w", "description": "d"}},
            AbortController(),
        )
    )
    assert result.is_error
    assert "runtime not configured" in result.content
