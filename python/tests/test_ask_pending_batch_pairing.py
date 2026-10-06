"""批次里混着"挂起待用户回答的 AskUserQuestion"时的配对契约（进程内真引擎，无付费调用）。

在册用例只测过**单条** ask（request/resolve/timeout/skip-ask/cancel），
没测过**同批还有别的工具**这一形状——而那正是结果被丢或投影留下悬空 tool_calls 的位置：
模型一次发起 [Read, AskUserQuestion, Glob]，中间那条要等人。
这里钉三条：
1. 挂起期间引擎**不得带着半批发下一枪**（模型第二轮在作答前不能开始）；
2. 作答后三条结果都要落库、配对正确，且答案不能被标成失败回执；
3. 用户关掉面板（cancel）也要给每条调用一个终态，投影不留悬空。

替身工具借真名（Read/Glob）：`permissions/policy.py` 对未知工具默认 ASK，
自定义名字会被权限层挡在门外，测不到编排与循环。
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.permission_coordinator import PermissionCoordinator
from engine.query_loop import query_loop
from engine.task_state import SessionTaskState
from model._openai_common import normalize_messages_for_openai, prune_orphan_tool_rows
from model.chunks import ModelChunk
from msgtypes.message import ToolUse, tool_result_message, user_message
from permissions.ask_store import default_ask_store
from permissions.store import PendingPermissionStore
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.ask_user_question_tool import AskUserQuestionTool
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry

ASK = "AskUserQuestion"
BATCH = [
    ("Read", {"file_path": "a.py"}),
    (ASK, {"question": "Which?", "options": ["a", "b"]}),
    ("Glob", {"pattern": "*.py"}),
]


class _ReadOnlySub:
    def __init__(self, name: str) -> None:
        self.name = name

    @staticmethod
    def is_read_only() -> bool:
        return True

    @staticmethod
    def is_concurrency_safe() -> bool:
        return True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": f"substitute for {self.name}",
            "input_schema": {"type": "object", "properties": {}},
        }

    async def execute(self, input: dict[str, Any], abort) -> ToolResult:
        return ToolResult(content=f"{self.name}|ran")


class _Client:
    """第一轮发起整批；之后只回文本（保证第二次 stream 一定是"作答之后"）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
        self.calls += 1
        if self.calls == 1:
            for i, (name, inp) in enumerate(BATCH):
                yield ModelChunk(kind="tool_use", tool_use=ToolUse(id=f"c{i}", name=name, input=inp))
            return
        yield ModelChunk(kind="text_delta", text="done")
        return


def _wire(store: MessageStore) -> list[dict]:
    """发射形状：assistant 的 tool_use 块要经 normalize 才变成 ``tool_calls``。

    直接拿 ``store.as_api_messages()`` 判配对会同时得假阴与假阳：
    内部形状里 assistant 没有 ``tool_calls`` 键 ⇒ 悬空恒空，
    而 ``prune_orphan_tool_rows`` 会把每一条结果都判成无主。
    """
    return prune_orphan_tool_rows(
        normalize_messages_for_openai(store.as_api_messages(), provider="deepseek", model="x")
    )[0]


def _dangling(api: list[dict]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(api):
        m = api[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = {str(c.get("id")) for c in m["tool_calls"] if c.get("id")}
            got: set[str] = set()
            j = i + 1
            while j < len(api) and api[j].get("role") == "tool":
                got.add(str(api[j].get("tool_call_id") or ""))
                j += 1
            out.extend(sorted(need - got))
            i = j
            continue
        i += 1
    return out


def _harness(tmp_path):
    ws = Path(tmp_path)
    (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
    reg = ToolRegistry(cwd=str(ws))
    reg.register(_ReadOnlySub("Read"))
    reg.register(AskUserQuestionTool())
    reg.register(_ReadOnlySub("Glob"))
    coord = PermissionCoordinator(
        store=PendingPermissionStore(),
        task_state=SessionTaskState(session_id="s-ask-batch"),
        session_id="s-ask-batch",
        turn_id="t1",
    )
    store = MessageStore([user_message("跑三个工具")])
    client = _Client()
    events: list[object] = []

    async def drive() -> None:
        async for ev in query_loop(
            store=store, model=client, tools=reg, prompt=PromptAssembler(),
            system_prompt=DEFAULT_SYSTEM, abort=AbortController(),
            budget=BudgetTracker(max_turns=4), coordinator=coord,
        ):
            events.append(ev)

    return store, client, coord, drive, events


async def _wait_pending(timeout: float = 10.0) -> None:
    asks = default_ask_store()
    for _ in range(int(timeout / 0.02)):
        if any(not it.resolved for it in asks._items.values()):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("AskUserQuestion 没有进入挂起态（用例没走到目标分支）")


def _drain_ask_store() -> None:
    asks = default_ask_store()
    asks._items.clear()
    asks._events.clear()


@pytest.fixture(autouse=True)
def _clean_ask_store():
    _drain_ask_store()
    yield
    _drain_ask_store()


def test_dangling_check_is_not_vacuous(tmp_path):
    """反 vacuity 控：整批结果丢失时配对断言必须点名；补回应答必须转干净。"""
    from msgtypes.message import assistant_text_message

    uses = [ToolUse(id=f"c{i}", name="Read", input={"file_path": "a.py"}) for i in range(3)]
    lost = MessageStore([user_message("go"), assistant_text_message("", tool_uses=uses)])
    w_lost = _wire(lost)
    assert _dangling(w_lost) == ["c0", "c1", "c2"], w_lost
    answered = MessageStore([
        user_message("go"),
        assistant_text_message("", tool_uses=uses),
    ])
    for i in range(3):
        answered.append(tool_result_message(f"c{i}", "Read", f"r{i}"))
    w_ok = _wire(answered)
    assert _dangling(w_ok) == [], w_ok
    assert prune_orphan_tool_rows(w_ok)[1] == []


@pytest.mark.asyncio
async def test_suspended_batch_does_not_fire_next_request(tmp_path):
    """挂起期间不得发下一枪：否则半批（只有 tool_calls 没有应答）会被厂商拒。"""
    store, client, coord, drive, _events = _harness(tmp_path)
    task = asyncio.create_task(drive())
    try:
        await _wait_pending()
        api = store.as_api_messages()
        # 整批还没收尾 ⇒ 第二次模型请求不能已经开始
        assert client.calls == 1, f"挂起中就发了下一枪（calls={client.calls}）"
        # 结果要么整批在、要么整批不在（不许留半批进历史）
        assert [r.get("role") for r in api] == ["user", "assistant"], api
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


@pytest.mark.asyncio
async def test_answered_batch_records_every_sibling(tmp_path):
    """作答后：三条调用都要有终态、逐槽配对，答案不能被标成失败。"""
    store, client, coord, drive, events = _harness(tmp_path)
    task = asyncio.create_task(drive())
    await _wait_pending()
    asks = default_ask_store()
    for rid, item in list(asks._items.items()):
        asks.resolve_answer(rid, "a")
    await asyncio.wait_for(task, timeout=20.0)

    api = _wire(store)
    tool_rows = [r for r in api if r.get("role") == "tool"]
    assert [r.get("tool_call_id") for r in tool_rows] == ["c0", "c1", "c2"], tool_rows
    assert _dangling(api) == []
    assert prune_orphan_tool_rows(api)[1] == []
    by_id = {r.get("tool_call_id"): str(r.get("content")) for r in tool_rows}
    assert by_id["c0"] == "Read|ran", by_id
    assert by_id["c2"] == "Glob|ran", by_id
    assert by_id["c1"] == "a", by_id
    # is_error 只在内部形状上带（normalize 会把 tool_result 摊平成字符串），
    # 所以"答案不能被标成失败"这条要回内部行判。
    inner = {
        str(b.get("tool_use_id")): bool(b.get("is_error"))
        for m in store.items
        if m.role == "tool" and isinstance(m.content, list)
        for b in m.content
        if isinstance(b, dict) and b.get("type") == "tool_result"
    }
    assert inner == {"c0": False, "c1": False, "c2": False}, f"用户答案/兄弟结果被记成失败回执：{inner}"
    assert any(type(e).__name__ == "FinalEvent" for e in events), events
    assert client.calls == 2


@pytest.mark.asyncio
async def test_dismissed_ask_still_closes_every_call(tmp_path):
    """用户关掉面板（cancel）也要给整批一个终态，投影不留悬空 tool_calls。"""
    store, client, coord, drive, _events = _harness(tmp_path)
    task = asyncio.create_task(drive())
    await _wait_pending()
    released = default_ask_store().cancel_pending_for_session("s-ask-batch", actor="panel_closed")
    assert released >= 1, "取消没有唤醒等待者（用例没走到目标分支）"
    await asyncio.wait_for(task, timeout=20.0)

    api = _wire(store)
    tool_rows = [r for r in api if r.get("role") == "tool"]
    assert len(tool_rows) == len(BATCH), f"取消后仍有调用没有终态：{[r.get('tool_call_id') for r in tool_rows]}"
    assert _dangling(api) == [], _dangling(api)
    assert prune_orphan_tool_rows(api)[1] == []
