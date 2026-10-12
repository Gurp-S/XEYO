from copy import deepcopy
import pytest

from engine.abort import AbortController
from memory.wsc_handoff_transaction import commit
from memory.wsc_handoff_bindings import basis
from memory.working import WorkingSnapshot
from msgtypes.message import Message, ToolUse
from session.compression_source import compression_messages
from session.message_store import MessageStore
from session.record_transcript import record_transcript_sync
from tools.tool_registry import ToolRegistry
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


async def prepared(tmp_path, alias=False):
    store = MessageStore([Message(role="user", id="spec", content="RF-683917是退款验收标记"),
                          Message(role="user", id="new", content="报告验收任务")])
    if alias:
        store.append(Message(role="user", id="alias-spec", content="RF-683917是退款验收标记"))
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    working = WorkingSnapshot(session_id="bindings")
    known = set()
    path = tmp_path / "transcript.jsonl"
    source = lambda: compression_messages(store, working)
    persist = lambda: record_transcript_sync(store.items, session_id="bindings", path=path, known_ids=known)
    initial = {"todos": [{"id": "report", "content": "验收报告", "activeForm": "验收报告", "status": "pending"}],
               "checkpoint": {"objective": "报告验收", "context_message_ids": ["spec"]}}
    async def initial_generation(rows): return ToolUse("prior", "TodoWrite", initial)
    await commit(source=source, generate=initial_generation, store=store, tools=registry, abort=AbortController(), persist=persist)
    if alias:
        # Ordinary explicit TodoWrite has the existing @latest_user contract.
        from msgtypes.message import assistant_text_message, tool_result_message
        use = ToolUse("alias", "TodoWrite", {**initial, "checkpoint": {"objective": "报告验收", "context_message_ids": ["@latest_user"]}})
        store.append(assistant_text_message("", [use]))
        result = await registry.run(use, AbortController())
        store.append(tool_result_message(use.id, use.name, result.content, execution=result.execution_metadata()))
        persist()
    return store, registry, source, persist, path, initial


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["retained", "omitted", "explicit_retire", "stale_base", "wrong_retire", "completed", "cleared"])
async def test_real_commit_cannot_silently_drop_previously_bound_spec(tmp_path, mode):
    store, tools, source, persist, path, state = await prepared(tmp_path)
    prefix, rows = path.read_bytes(), deepcopy(source())
    candidate = deepcopy(state)
    if mode not in {"retained", "completed"}:
        candidate["checkpoint"]["context_message_ids"] = ["new"]
    if mode in {"explicit_retire", "stale_base", "wrong_retire"}:
        candidate["context_disposition"] = {"base_checkpoint_message_id": basis(source())["base_checkpoint_message_id"],
            "retired_context_message_ids": ["spec"]}
        if mode == "stale_base": candidate["context_disposition"]["base_checkpoint_message_id"] = "invented"
        if mode == "wrong_retire": candidate["context_disposition"]["retired_context_message_ids"] = ["new"]
    if mode == "completed": candidate["todos"][0]["status"] = "completed"
    if mode == "cleared": candidate["todos"] = []
    async def generated(rows): return ToolUse("next", "TodoWrite", candidate)
    async def invoke():
        return await commit(source=source, generate=generated, store=store, tools=tools, abort=AbortController(), persist=persist)
    if mode in {"omitted", "stale_base", "wrong_retire"}:
        with pytest.raises(ValueError, match="handoff_.*context.*"): await invoke()
        assert source() == rows and path.read_bytes() == prefix
    else:
        assert (await invoke())["call_id"] == "next"
        assert path.read_bytes().startswith(prefix)
        assert source()[:len(rows)] == rows
        if mode == "explicit_retire":
            assert source()[-2]["content"][0]["input"]["context_disposition"]["retired_context_message_ids"] == ["spec"]


@pytest.mark.asyncio
async def test_alias_is_bound_at_original_checkpoint_not_new_followup(tmp_path):
    store, tools, source, persist, path, state = await prepared(tmp_path, alias=True)
    store.append(Message(role="user", id="later", content="继续"))
    assert basis(source())["bound_context_message_ids"] == ["alias-spec"]


@pytest.mark.asyncio
async def test_large_spec_binding_remains_deferred_in_actual_projection(tmp_path):
    from memory.wsc_projection import production_params
    from synaptic.project import project
    store, tools, source, persist, path, state = await prepared(tmp_path)
    # Construct a separate long-source history; never modify a published row.
    other = MessageStore([Message(role="user", id="spec", content="规范记录\n" * 10000 + "RF-683917"),
                          Message(role="user", id="new", content="当前报告")])
    working = WorkingSnapshot()
    other_source = lambda: compression_messages(other, working)
    async def generated(rows): return ToolUse("long-checkpoint", "TodoWrite", state)
    await commit(source=other_source, generate=generated, store=other, tools=tools, abort=AbortController(), persist=lambda: None)
    projected = project(other_source(), region_end=len(other.items), params=production_params(), view_path=tmp_path / "cold.txt")
    assert "RF-683917" not in projected.text
    assert 'message_id="spec"' in projected.text or '"message_id":"spec"' in projected.text
    assert "RF-683917" in open(projected.view_path, encoding="utf-8").read()


@pytest.mark.asyncio
async def test_model_receives_binding_error_and_restores_source_before_real_commit(tmp_path):
    import json
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    store, tools, source, persist, path, state = await prepared(tmp_path)
    original, prefix = deepcopy(source()), path.read_bytes()
    requests, usage = [], []
    class Client:
        last_usage = None
        async def stream(self, messages, schemas, abort):
            attempt = len(requests)
            requests.append(deepcopy(messages))
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 1}
            if attempt:
                error = json.loads(messages[-1]["content"][0]["content"])
                assert error["error"] == "handoff_bound_context_disposition_missing"
                assert error["omitted_context_message_ids"] == ["spec"]
            candidate = deepcopy(state)
            candidate["checkpoint"]["context_message_ids"] = ["new", "spec"] if attempt else ["new"]
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"generated-{attempt}", "TodoWrite", candidate))
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    async def generated(rows):
        return await generate(Model(), [{"role": "user", "content": "继续报告"}], rows,
            TodoWriteTool().schema(), AbortController(), account=usage.append)
    result = await commit(source=source, generate=generated, store=store, tools=tools, abort=AbortController(), persist=persist)
    assert result["call_id"] == "generated-1" and len(usage) == 2
    assert source()[:len(original)] == original and path.read_bytes().startswith(prefix)
    assert all(use["id"] != "generated-0" for row in source() for use in row.get("content", [])
               if isinstance(row.get("content"), list) and use.get("type") == "tool_use")
