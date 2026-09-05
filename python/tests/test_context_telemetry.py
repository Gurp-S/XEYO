from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from model.chunks import ModelChunk
from model.openai_compat import (
    context_limit_from_usage,
    context_tokens_from_usage,
)
from msgtypes.events import ContextCompressionEvent, UsageEvent
from msgtypes.message import user_message
from prompt.assembler import PromptAssembler
from session.message_store import MessageStore
from tools.tool_registry import ToolRegistry


class _UsageModel:
    last_usage = {"prompt_tokens": 91, "completion_tokens": 7}
    last_context_tokens = 91
    context_limit = 128_000

    async def stream(self, messages, tools, abort):
        del messages, tools
        abort.raise_if_aborted()
        yield ModelChunk(kind="text_delta", text="ok")


def test_context_tokens_use_real_vendor_usage_fields() -> None:
    assert context_tokens_from_usage({"prompt_tokens": 91}) == 91
    assert context_tokens_from_usage({"input_tokens": 83}) == 83
    assert context_tokens_from_usage({"prompt_tokens": 0, "input_tokens": 0}) is None


def test_context_limit_accepts_explicit_provider_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XEYO_CONTEXT_LIMIT_TOKENS", "131072")
    assert context_limit_from_usage({}) == 131072
    assert context_limit_from_usage({"context_window": 262144}) == 262144
    assert context_limit_from_usage({"context_window": 0}) == 131072


@pytest.mark.asyncio
async def test_query_loop_emits_usage_context_telemetry() -> None:
    events = []
    async for event in query_loop(
        store=MessageStore([user_message("hello")]),
        model=_UsageModel(),
        tools=ToolRegistry(),
        prompt=PromptAssembler(),
        system_prompt="You are a test assistant.",
        abort=AbortController(),
        budget=BudgetTracker(max_turns=2),
    ):
        events.append(event)

    usages = [event for event in events if isinstance(event, UsageEvent)]
    assert usages
    # DSH ``contextPressure.projectdTokens`` 口径：分子 = 当前投影 token 数（含压缩，立即反映），
    # 不再是厂商 prompt_tokens=91（若投影为 0 则回退厂商值）。
    assert usages[0].context_tokens > 0
    assert usages[0].context_limit == 128_000


def test_scale_breakdown_sums_to_total() -> None:
    from engine.query_loop import _scale_breakdown
    from collections import OrderedDict

    chars = OrderedDict(
        [
            ("system", 80),
            ("rules", 0),
            ("memory_behavior", 0),
            ("tool_definitions", 0),
            ("memory_index", 0),
            ("summary", 0),
            ("conversation", 20),
        ]
    )
    out = _scale_breakdown(chars, 1000)
    assert out
    # 各类别顺序稳定，且总和等于厂商权威 prompt_tokens
    assert [b["category"] for b in out] == ["system", "conversation"]
    assert sum(b["tokens"] for b in out) == 1000
    assert out[0]["tokens"] > 0 and out[1]["tokens"] > 0


@pytest.mark.asyncio
async def test_query_loop_emits_context_breakdown() -> None:
    from engine.budget import BudgetTracker

    events = []
    async for event in query_loop(
        store=MessageStore([user_message("hello")]),
        model=_UsageModel(),
        tools=ToolRegistry(),
        prompt=PromptAssembler(),
        system_prompt="You are a test assistant.",
        abort=AbortController(),
        budget=BudgetTracker(max_turns=2),
        system_breakdown=[
            {"category": "system", "label": "System prompt", "chars": 50},
            {"category": "rules", "label": "Rules", "chars": 30},
        ],
    ):
        events.append(event)

    usages = [event for event in events if isinstance(event, UsageEvent)]
    assert usages
    bd = usages[0].context_breakdown
    assert bd
    # DSH ``contextPressure.projectdTokens`` 口径：分子 = 当前投影 token 数（含压缩，立即反映），
    # 不再等于厂商 prompt_tokens=91。构成明细（breakdown）是启发式组成，总和 = 投影分子。
    assert sum(b["tokens"] for b in bd) == usages[0].context_tokens
    assert usages[0].context_tokens > 0
    assert any(b["category"] == "system" for b in bd)
    assert any(b["category"] == "rules" for b in bd)


def test_compression_event_wire_fields_are_stable() -> None:
    event = ContextCompressionEvent(
        phase="complete",
        source="automatic",
        context_tokens=1200,
        context_limit=128000,
    )
    assert event.phase == "complete"
    assert event.source == "automatic"
    assert event.context_tokens == 1200
    assert event.context_limit == 128000
