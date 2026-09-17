import sys
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import ResultEvent, StoppedEvent, ToolCallEvent, ToolResultEvent
from msgtypes.message import ToolUse
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


class TwentyToolThenFinishModel:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[dict]] = []

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        abort: AbortController,
    ) -> AsyncIterator[ModelChunk]:
        self.calls += 1
        self.messages.append(messages)
        abort.raise_if_aborted()
        if self.calls == 1:
            for index in range(20):
                yield ModelChunk(
                    kind="tool_use",
                    tool_use=ToolUse(
                        id=f"call_{index}_{uuid4().hex[:8]}",
                        name="echo",
                        input={"text": str(index)},
                    ),
                )
            return
        yield ModelChunk(kind="text_delta", text="已完成")


class PersistentSixteenToolModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        abort: AbortController,
    ) -> AsyncIterator[ModelChunk]:
        self.calls += 1
        abort.raise_if_aborted()
        # 输入必须互不相同：本测试验证的是 Tool Call 预算与共享 grace，
        # 若用相同签名会被 repeat guard 以重复调用为由拦截而失真。
        for index in range(16):
            yield ModelChunk(
                kind="tool_use",
                tool_use=ToolUse(
                    id=f"call_{self.calls}_{index}_{uuid4().hex[:8]}",
                    name="echo",
                    input={"text": f"loop-{self.calls}-{index}"},
                ),
            )


def _engine(model: object, *, max_turns: int = 50) -> QueryEngine:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return QueryEngine(
        {
            "cwd": ".",
            "tools": reg,
            "model_client": model,  # type: ignore[typeddict-item]
            "max_turns": max_turns,
            "max_tool_calling": 16,
        }
    )


def _system_text(messages: list[dict]) -> str:
    return "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "system"
    )


def _request_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or ""))
        else:
            parts.append(str(content))
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_max_tool_calling_executes_only_sixteen_and_pairs_skips():
    model = TwentyToolThenFinishModel()
    eng = _engine(model)
    events = [event async for event in eng.submit("go")]

    calls = [event for event in events if isinstance(event, ToolCallEvent)]
    results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(calls) == 16
    assert len(results) == 20
    assert sum(event.is_error for event in results) == 4
    assert all(not event.is_error for event in results[:16])
    assert all(event.is_error for event in results[16:])
    assert model.calls == 2
    assert eng._session.budget.turn_count == 2

    # 2026-09-15 用户裁定撤销 `runtime_notice` / `wrap_up` 两块模型可见文本
    # （docs/synaptic-compression.md §14.3；`engine/budget.py` 的机制**全部保留**，
    # 只是不再讲给模型听）。本文件原来的断言是「该文本在第 2 次请求里出现恰好 1 次」，
    # 撤块后**在结构上永远为假**（`run_pre_llm_inject` 已无 `runtime_notice` 参数、
    # 模块内也无该渲染器）⇒ 按撤块裁定翻成**负向契约**：任何模型可见面都不得出现它。
    # 同款翻正在 `tests/test_t_now_budget_text_revoked.py` 与 `test_pre_llm_inject.py`。
    warning = "工具调用数已接近上限。"
    assert _system_text(model.messages[0]).count(warning) == 0
    assert _system_text(model.messages[1]).count(warning) == 0
    assert _request_text(model.messages[0]).count(warning) == 0
    assert _request_text(model.messages[1]).count(warning) == 0
    assert warning not in "\n".join(
        str(message.content) for message in eng._session.messages.items
    )
    final = [event for event in events if isinstance(event, ResultEvent)]
    assert final and final[-1].subtype == "success"
    assert final[-1].result == "已完成"


@pytest.mark.asyncio
async def test_max_tool_calling_uses_shared_three_turn_grace_then_stops():
    model = PersistentSixteenToolModel()
    eng = _engine(model)
    events = [event async for event in eng.submit("go")]

    stopped = [event for event in events if isinstance(event, StoppedEvent)]
    assert stopped and stopped[-1].reason == "max_tool_calling"
    # 连续 2 轮 (streak=2) 顶满单轮工具配额才进入工具收尾窗口（grace-cliff 修复）。
    # 轮次：turn1 (顶满, streak=1) / turn2 (streak=2, 进入 grace) /
    #       turn3 (grace 内, grace_turns_used 从下一轮起计) / turn4-6 (3 个 grace 轮) /
    #       turn7 (硬停前的禁工具 wrap-up)。共 7 次模型请求。
    assert model.calls == 7
    assert eng._session.budget.turn_count == 7
    assert eng._session.budget.grace_turns_used == 4
    final = [event for event in events if isinstance(event, ResultEvent)]
    assert final and final[-1].subtype == "error_max_tool_calling"
    assert final[-1].is_error is True
