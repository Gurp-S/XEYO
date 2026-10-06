"""预算耗尽这一条出口，落库历史也必须是厂商合法形状（进程内真引擎，无付费调用）。

按停（`test_interrupt_turn_store_valid.py`）与挂起待批（`test_ask_pending_batch_pairing.py`）
之后剩下的第三条出口：`BudgetTracker(max_turns=…)` 到点时循环正好停在
"assistant 已发 tool_calls、结果尚未写回"的位置 —— 那会留下悬空 `tool_calls`，
下一次提交（或重启后 resume）整会话 400。

2026-10-04 实测：max_turns=1/2/3 三档都以 `StoppedEvent` 正常收尾、无异常、
无主结果 0、悬空 0，且 assistant 声明的调用数与实际结果行数逐档相等（10/10、12/12、14/14）。
本文件只钉投影形状，不钉轮数；轮数按 `engine/budget.py::prepare_next_turn` 是
`max_turns + 1（首次越过上限那一枪仍放行，随后 `_start_grace` 建立收尾窗口）+ MAX_GRACE_TURNS(3)`
⇒ 三档实测 5/6/7 与该式一致（既有设计，非缺陷）。
"""

import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from model._openai_common import normalize_messages_for_openai, prune_orphan_tool_rows
from model.chunks import ModelChunk
from msgtypes.message import ToolUse, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.catalog import build_default_registry


class _AlwaysCallsTools:
    """每轮都发两个只读工具调用，把循环一直推到预算耗尽。"""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
        self.calls += 1
        yield ModelChunk(kind="tool_use", tool_use=ToolUse(id=f"c{self.calls}a", name="getTime", input={}))
        yield ModelChunk(
            kind="tool_use",
            tool_use=ToolUse(id=f"c{self.calls}b", name="Glob", input={"pattern": "*.py"}),
        )
        return


def _dangling(wire: list[dict]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(wire):
        m = wire[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = {str(c.get("id")) for c in m["tool_calls"] if c.get("id")}
            got: set[str] = set()
            j = i + 1
            while j < len(wire) and wire[j].get("role") == "tool":
                got.add(str(wire[j].get("tool_call_id") or ""))
                j += 1
            out.extend(sorted(need - got))
            i = j
            continue
        i += 1
    return out


@pytest.mark.parametrize("max_turns", [1, 3])
@pytest.mark.asyncio
async def test_budget_exhaustion_leaves_valid_history(tmp_path, max_turns):
    reg = build_default_registry(cwd=str(tmp_path))
    store = MessageStore([user_message("循环调用工具直到预算耗尽")])
    client = _AlwaysCallsTools()
    events: list[Any] = []
    async for ev in query_loop(
        store=store, model=client, tools=reg, prompt=PromptAssembler(),
        system_prompt=DEFAULT_SYSTEM, abort=AbortController(),
        budget=BudgetTracker(max_turns=max_turns),
    ):
        events.append(ev)

    # 前置自证：确实走到"多轮工具 + 预算耗尽"那条出口
    assert client.calls > max_turns, f"没走到预算出口（模型只被调 {client.calls} 次）"
    assert any(type(e).__name__ == "StoppedEvent" for e in events), [type(e).__name__ for e in events]

    wire = normalize_messages_for_openai(store.as_api_messages(), provider="deepseek", model="x")
    pruned, dropped = prune_orphan_tool_rows(wire)
    assert dropped == [], f"有无主结果被最后一公里吃掉：{dropped}"
    assert _dangling(pruned) == []
    declared = sum(
        len(r.get("tool_calls") or []) for r in pruned if r.get("role") == "assistant"
    )
    results = sum(1 for r in pruned if r.get("role") == "tool")
    assert declared == results > 0, (declared, results)
