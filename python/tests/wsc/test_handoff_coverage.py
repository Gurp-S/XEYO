from copy import deepcopy

import pytest

from memory.wsc_handoff_coverage import Coverage, PresentedHandoff, validated


def test_exact_ranges_merge_but_reading_title_does_not_prove_complete_source():
    sources = [{"id": "spec", "role": "user", "content": "标题\n" + "细节" * 100 + "尾部规范"}]
    tracker = Coverage(sources)
    tracker.source_result({"message_id": "spec", "offset": 0, "content": "标题\n", "text_complete": True})
    tracker.source_result({"message_id": "spec", "offset": 3, "content": "细节细节"})
    row = tracker.record(["spec"])["sources"][0]
    assert row["presented_ranges"] == [[0, 7]] and row["complete"] is False
    assert validated(tracker.record(["spec"]), sources)["sources"][0]["complete"] is False


def test_query_passages_count_only_exact_original_characters():
    sources = [{"id": "spec", "role": "user", "content": "开头 中间 尾部"}]
    tracker = Coverage(sources)
    tracker.source_result({"message_id": "spec", "query": "尾部", "passages": [
        {"offset": 6, "content": "尾部"}, {"offset": 0, "content": "虚构"}]})
    assert tracker.record(["spec"])["sources"][0]["presented_ranges"] == [[6, 8]]


def test_metadata_is_bound_to_unique_immutable_source_and_completeness_is_recomputed():
    sources = [{"id": "spec", "role": "user", "content": "真实规范"}]
    tracker = Coverage(sources)
    record = tracker.record(["spec"])
    record["sources"][0]["complete"] = True
    assert validated(record, sources)["sources"][0]["complete"] is False
    with pytest.raises(ValueError, match="presentation_invalid"):
        validated(record, sources + deepcopy(sources))
    with pytest.raises(ValueError, match="presentation_invalid"):
        validated(record, [{"id": "spec", "role": "user", "content": "被替换规范"}])
    record["sources"][0]["presented_ranges"] = [[0, 999]]
    with pytest.raises(ValueError, match="presentation_invalid"):
        validated(record, sources)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_isolated_generation_coverage_is_persisted_and_projects_after_actual_reload(tmp_path, monkeypatch, native):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    import importlib
    transcript = importlib.import_module("session.record_transcript")
    from synaptic.graph import build_graph
    from synaptic.task_checkpoint import project_state
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    text = "规范标题\n" + "来源细节\n" * 10000 + "末尾验收标准"
    store = MessageStore([Message(role="user", id="spec", content=text)])
    for index in range(35):
        store.append(Message(role="assistant", content="归档负载" + str(index) + "x" * 2000))
    working = WorkingSnapshot()
    source = lambda: compression_messages(store, working)
    original = deepcopy(source())
    tools = ToolRegistry(cwd=str(tmp_path))
    tools.register(TodoWriteTool(cwd=str(tmp_path)))
    path = tmp_path / "transcript.jsonl"
    known = set()

    def persist():
        transcript.record_transcript_sync(store.items, session_id="coverage", path=path, known_ids=known)

    persist()
    prefix = path.read_bytes()
    sent = []
    class Client:
        last_usage = None
        async def stream(self, messages, schemas, abort):
            sent.append(deepcopy(messages))
            if len(sent) == 1:
                use = ToolUse("read-spec", "HandoffSource", {"message_id": "spec", "offset": 0, "limit": 5})
            else:
                use = ToolUse("declare-spec", "TodoWrite", {"todos": [{"id": "task", "content": "验收", "status": "pending", "activeForm": "验收"}],
                    "checkpoint": {"objective": "规范验收", "context_message_ids": ["spec"]}})
            yield ModelChunk(kind="tool_use", tool_use=use)
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    async def declaration(rows):
        use = await generate(Model(), [{"role": "user", "content": "继续验收"}], rows,
                             TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
        assert isinstance(use, PresentedHandoff)
        assert use.presentation["sources"][0]["presented_ranges"] == [[0, 5]]
        return use
    await commit(source=source, generate=declaration, store=store, tools=tools, abort=AbortController(), persist=persist)
    assert source()[:len(original)] == original and path.read_bytes().startswith(prefix)
    restored = transcript.load_transcript(path)
    from session.transcript_blobs import resolve_transcript_rows
    restored = resolve_transcript_rows(restored, anchor=path)
    # Source identity metadata is reconstructed as on normal restore.
    rows = [dict(row, message_id=row.get("id")) for row in restored]
    state, _ = project_state(rows, build_graph(rows))
    partial = state["partially_presented_sources"][0]
    assert partial["message_id"] == "spec" and partial["presented_ranges"] == [[0, 5]]
    assert partial["total_characters"] == len(text) and partial["complete"] is False
    assert "末尾验收标准" not in str(sent)
    assert state["items"][0]["status"] == "pending"
    from memory.runtime import force_compact
    from memory import wsc_projection
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    wsc_projection._STATE.clear()
    emitted = force_compact(rows, WorkingSnapshot(session_id="coverage-" + str(native)), cwd=tmp_path)
    assert '"handoff_presented_ranges":[[0,5]]' in emitted[0]["content"]
    assert '"source_total_characters":' + str(len(text)) in emitted[0]["content"]
    assert path.read_bytes().startswith(prefix)
