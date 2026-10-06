"""畸形 tool_use id 下的投影不变量（进程内真引擎，无付费调用）。

模型（尤其弱模型）会发出重复 id、空 id 的 tool_use。这里不评判"该不该执行第二次"，
只钉一条硬不变量：**任何形状的 tool_use 都不能让发射投影留下"有调用没应答"或"有应答没调用"**
——那是 2026-09-20 之后每次出现就整会话 400 的形状。

顺带记录现状（不是缺陷裁定）：`engine/query_loop.py::_admit_tool_use`（:1347）对重复 id 是
**静默丢弃**（assistant 行里也只留第一个块 ⇒ 投影自洽，不会 400），
与相邻两条"占配额但不执行"的分支（生命周期收尾 / wrap 配额耗尽都会写一条失败回执）不同。
要不要给模型一句"你第二次用了同一个 id，已被忽略"属模型可见文本，等裁定；本文件只钉投影形状。
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


class _Scripted:
    """第一轮按脚本发调用（可选先流一段正文）；之后只回文本。"""

    def __init__(self, uses: list[ToolUse], *, lead_text: bool = False) -> None:
        self.uses = uses
        self.lead_text = lead_text
        self.calls = 0

    async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
        self.calls += 1
        if self.calls == 1:
            if self.lead_text:
                yield ModelChunk(kind="text_delta", text="我先看一下")
            for tu in self.uses:
                yield ModelChunk(kind="tool_use", tool_use=tu)
            return
        yield ModelChunk(kind="text_delta", text="收尾")
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


async def _run(tmp_path, uses: list[ToolUse]) -> tuple[MessageStore, list[Any]]:
    reg = build_default_registry(cwd=str(tmp_path))
    store = MessageStore([user_message("发这些调用")])
    events: list[Any] = []
    async for ev in query_loop(
        store=store, model=_Scripted(uses), tools=reg, prompt=PromptAssembler(),
        system_prompt=DEFAULT_SYSTEM, abort=AbortController(),
        budget=BudgetTracker(max_turns=4),
    ):
        events.append(ev)
    return store, events


def _wire(store: MessageStore):
    pruned, dropped = prune_orphan_tool_rows(
        normalize_messages_for_openai(store.as_api_messages(), provider="deepseek", model="x")
    )
    return pruned, dropped


@pytest.mark.asyncio
async def test_duplicate_tool_use_ids_keep_projection_valid(tmp_path):
    uses = [
        ToolUse(id="dup", name="getTime", input={}),
        ToolUse(id="dup", name="Glob", input={"pattern": "*.py"}),
    ]
    store, events = await _run(tmp_path, uses)
    pruned, dropped = _wire(store)
    assert dropped == [], f"有无主结果被吃掉：{dropped}"
    assert _dangling(pruned) == []
    # 同 id 只应答一次：出现第二条同 id 结果同样会让请求体非法
    ids = [r.get("tool_call_id") for r in pruned if r.get("role") == "tool"]
    assert len(ids) == len(set(ids)), f"同 id 结果重复：{ids}"
    assert any(type(e).__name__ == "FinalEvent" for e in events), [type(e).__name__ for e in events]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["", "   "], ids=["empty", "whitespace"])
async def test_missing_tool_use_id_fails_closed_without_bricking_history(tmp_path, bad_id):
    """空/纯空白 id：引擎按协议错误拒绝（不"洗"成合法调用），且**已落库的半轮正文不会留下坏形状**。

    实测（2026-10-04）：抛 `ModelProtocolError: tool_use event is missing id`；
    历史停在 `user, assistant`（模型这轮已流出的正文照常落库），
    无 tool_calls 悬空、无无主结果 ⇒ 下一枪请求体仍合法，会话不报废。
    """
    from engine.model_events import ModelProtocolError

    reg_cwd = str(tmp_path)
    store_holder: list[MessageStore] = []

    async def drive() -> None:
        reg = build_default_registry(cwd=reg_cwd)
        store = MessageStore([user_message("发这些调用")])
        store_holder.append(store)
        async for _ in query_loop(
            store=store, model=_Scripted([ToolUse(id=bad_id, name="getTime", input={})], lead_text=True),
            tools=reg, prompt=PromptAssembler(), system_prompt=DEFAULT_SYSTEM,
            abort=AbortController(), budget=BudgetTracker(max_turns=4),
        ):
            pass

    with pytest.raises(ModelProtocolError):
        await drive()

    pruned, dropped = _wire(store_holder[0])
    assert dropped == []
    assert _dangling(pruned) == []
    assert [r.get("role") for r in pruned] == ["user", "assistant"], pruned
