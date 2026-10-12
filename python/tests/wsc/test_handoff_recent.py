from copy import deepcopy
import json
import pytest

from memory.wsc_handoff_recent import materialize, PER_ROLE, MAX_BYTES


def test_tool_flood_does_not_hide_recent_plan_and_user_authorization():
    rows = [{"id": "old", "role": "user", "content": "旧要求"}]
    rows += [{"id": f"u{i}", "role": "user", "content": f"用户阶段{i}"} for i in range(PER_ROLE)]
    rows.append({"id": "plan", "role": "assistant", "content": "完整当前计划与验收来源"})
    rows += [{"id": f"r{i}", "role": "tool", "content": "工作回执"} for i in range(500)]
    before = deepcopy(rows)
    result = materialize(rows)
    assert [row["message_id"] for row in result["sources"]] == [f"u{i}" for i in range(PER_ROLE)] + ["plan"]
    assert result["sources"][-1]["content"] == "完整当前计划与验收来源"
    assert rows == before


def test_oversize_and_ambiguous_sources_defer_whole_text_without_fake_preview():
    rows = [{"id": "huge", "role": "user", "content": "规范" * MAX_BYTES},
            {"id": "dup", "role": "user", "content": "a"}, {"id": "dup", "role": "assistant", "content": "b"},
            {"id": "new", "role": "assistant", "content": "当前计划"}]
    result = materialize(rows)
    assert [row["message_id"] for row in result["sources"]] == ["new"]
    assert set(result["deferred_message_ids"]) == {"huge", "dup"}


def test_capacity_admission_and_chronology_are_independent_of_recent_selection_order():
    rows = [{"id": str(i), "role": "user", "content": str(i)} for i in range(8)]
    result = materialize(rows, admit=lambda records, deferred: len(records) <= 3)
    assert [row["message_id"] for row in result["sources"]] == ["5", "6", "7"]
    assert set(result["deferred_message_ids"]) == {"0", "1", "2", "3", "4"}


def test_engine_notes_are_not_recent_task_text():
    assert not materialize([{"id": "note", "role": "user", "content": "机器注入", "note_key": "world_state"}])["sources"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_dedicated_recent_evidence_is_opt_in_and_counts_only_exact_presented_text(enabled):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    sources = [{"role": "assistant", "id": "plan", "content": "完整任务计划与未完成步骤"}]
    messages = [{"role": "user", "content": "继续"}]
    before = deepcopy((sources, messages))
    class Client:
        last_usage = None
        async def stream(self, request, tools, abort):
            marker = "近期原文证据（未声明为当前权威）="
            assert (marker in request[-1]["content"]) is enabled
            if enabled:
                evidence = json.loads(request[-1]["content"].split(marker)[1])
                assert evidence["sources"][0]["content"] == sources[0]["content"]
            yield ModelChunk(kind="tool_use", tool_use=ToolUse("declare", "TodoWrite",
                {"todos": [], "checkpoint": {"objective": "", "context_message_ids": ["plan"]}}))
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    result = await generate(Model(), messages, sources, TodoWriteTool().schema(),
                            AbortController(), account=lambda usage: None,
                            recent_text_sources=enabled)
    records = result.presentation["sources"]
    assert any(record["complete"] for record in records) is enabled
    assert (sources, messages) == before
