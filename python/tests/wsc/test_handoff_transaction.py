from copy import deepcopy
import pytest

from memory.wsc_handoff_transaction import commit
from engine.abort import AbortController
from memory.working import WorkingSnapshot
from session.compression_source import compression_messages
from msgtypes.message import Message, ToolUse
from session.message_store import MessageStore
from tools.tool_registry import ToolRegistry
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
from tools.base_tool import ToolResult


def setup(tmp_path):
    store = MessageStore([Message(role="user", id="spec", content="规范：写报告并关联回执")])
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    state = {"todos": [{"id": "report", "content": "写报告", "status": "pending", "activeForm": "写报告"}],
             "checkpoint": {"objective": "完成报告", "context_message_ids": ["spec"]}}
    return store, registry, state


@pytest.mark.asyncio
async def test_actual_task_tool_commits_durable_pair_before_compaction(tmp_path):
    store, registry, state = setup(tmp_path)
    persisted = []
    async def generate(rows):
        assert rows[0]["message_id"] == "spec"
        return ToolUse("handoff-real", "TodoWrite", state)
    result = await commit(source=lambda: compression_messages(store, WorkingSnapshot()), generate=generate, store=store, tools=registry,
                          abort=AbortController(), persist=lambda: persisted.append(deepcopy(store.as_api_messages())))
    assert result["call_id"] == "handoff-real" and result["task_count"] == 1
    assert len(persisted) == 2 and len(persisted[0]) == 2 and len(persisted[1]) == 3
    assert persisted[0][-1]["content"][0]["type"] == "tool_use"
    assert persisted[1][-1]["content"][0]["is_error"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["bad_source", "source_changed", "cancelled", "persist_failed"])
async def test_failed_generation_or_publication_never_produces_success_receipt(tmp_path, failure):
    store, registry, state = setup(tmp_path)
    abort = AbortController()
    async def generate(rows):
        if failure == "bad_source": state["checkpoint"]["context_message_ids"] = ["invented"]
        if failure == "source_changed": store.append(Message(role="user", content="新请求"))
        if failure == "cancelled": abort.abort()
        return ToolUse("handoff-failed", "TodoWrite", state)
    def persist():
        if failure == "persist_failed": raise OSError("fixture_publish_failed")
    with pytest.raises((ValueError, OSError)):
        await commit(source=lambda: compression_messages(store, WorkingSnapshot()), generate=generate, store=store, tools=registry, abort=abort, persist=persist)
    from synaptic.todo_snapshot import latest_todo_snapshot
    assert latest_todo_snapshot(store.as_api_messages()).observed is False


@pytest.mark.asyncio
async def test_actual_tool_rejection_is_recorded_without_committing_state(tmp_path):
    store, registry, state = setup(tmp_path)
    class Rejected(TodoWriteTool):
        async def execute(self, input, abort):
            return ToolResult("Permission denied: fixture", is_error=True)
    registry.register(Rejected(cwd=str(tmp_path)))
    async def generate(rows): return ToolUse("denied", "TodoWrite", state)
    with pytest.raises(ValueError, match="handoff_commit_failed"):
        await commit(source=lambda: compression_messages(store, WorkingSnapshot()), generate=generate, store=store, tools=registry,
                     abort=AbortController(), persist=lambda: None)
    assert store.as_api_messages()[-1]["content"][0]["is_error"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_newly_committed_protected_tail_handoff_covers_real_force(monkeypatch, tmp_path, native):
    from memory.runtime import force_compact
    from memory import wsc_projection
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    wsc_projection._STATE.clear()
    store, registry, state = setup(tmp_path)
    for i in range(35):
        store.append(Message(role="assistant", content="归档负载 " + str(i) + "x" * 2000))
    working = WorkingSnapshot(session_id="handoff-tail-" + str(native))
    source = lambda: compression_messages(store, working)
    original_prefix = deepcopy(source())
    async def generate(rows): return ToolUse("handoff-before-force", "TodoWrite", state)
    await commit(source=source, generate=generate, store=store, tools=registry,
                 abort=AbortController(), persist=lambda: None)
    actual = force_compact(source(), working, cwd=tmp_path)
    assert 0 < working.compact_cursor <= len(original_prefix)
    assert "完成报告" in actual[0]["content"]
    assert "规范：写报告并关联回执" in actual[0]["content"]
    assert source()[:len(original_prefix)] == original_prefix
    assert "handoff-before-force" in str(actual[1:])
