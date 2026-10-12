from copy import deepcopy

import pytest

from memory.wsc_handoff_fact_disposition import basis, validate, DispositionError
from tests.wsc.test_task_phase import declaration, sources, DURABLE, DESIGN
from tests.wsc.test_task_continuity import receipt


def prepared():
    raw = declaration()
    rows = sources() + receipt("checkpoint", raw["todos"], raw["checkpoint"])
    rows[-1]["id"] = "base"
    rows.append({"id": "next", "role": "user", "content": "完成实施，继续汇报；测试限制取消。"})
    return rows, raw


def retire(raw):
    raw["checkpoint"]["constraints"].pop()
    raw["checkpoint"]["phase_state"]["fact_scopes"]["constraints"].pop()
    raw["fact_disposition"] = {"base_checkpoint_message_id": "base", "retired_facts": [
        {"field": "constraints", "quote": DURABLE, "event_message_ids": ["next"]}]}


def test_task_fact_preserved_and_historical_phase_fact_not_promoted():
    rows, raw = prepared()
    before = deepcopy(rows)
    assert basis(rows)["task_facts"] == [{"field": "constraints", "quote": DURABLE}]
    validate(raw, rows)
    assert rows == before
    assert DESIGN not in str(basis(rows))


@pytest.mark.parametrize("change", ["omission", "phase_demotion", "scope_removal", "short_quote"])
def test_source_ids_retained_do_not_allow_task_fact_to_disappear(change):
    rows, raw = prepared()
    if change == "omission":
        raw["checkpoint"]["constraints"].pop()
        raw["checkpoint"]["phase_state"]["fact_scopes"]["constraints"].pop()
    elif change == "phase_demotion":
        raw["checkpoint"]["phase_state"]["fact_scopes"]["constraints"][-1] = {"kind": "phase", "phase_id": "implementation"}
    elif change == "scope_removal":
        del raw["checkpoint"]["phase_state"]
    else:
        raw["checkpoint"]["constraints"][-1]["quote"] = "金额只能使用整数分"
    with pytest.raises(DispositionError, match="disposition_missing"):
        validate(raw, rows)


def test_explicit_retirement_is_base_anchored_and_does_not_mutate_old_receipt():
    rows, raw = prepared()
    before = deepcopy(rows)
    retire(raw)
    validate(raw, rows)
    assert rows == before
    raw["fact_disposition"]["base_checkpoint_message_id"] = "previous"
    with pytest.raises(DispositionError, match="stale_base"):
        validate(raw, rows)


@pytest.mark.parametrize("event", ["permit", "missing", "duplicate", "machine", "tool"])
def test_retirement_requires_unique_new_text_event(event):
    rows, raw = prepared()
    retire(raw)
    raw["fact_disposition"]["retired_facts"][0]["event_message_ids"] = [event]
    if event == "duplicate": rows += [{"id": event, "role": "user", "content": "取消"}] * 2
    if event == "machine": rows.append({"id": event, "role": "user", "content": "取消", "note_key": "world_state"})
    if event == "tool": rows.append({"id": event, "role": "tool", "content": "取消"})
    with pytest.raises(DispositionError, match="event_invalid"):
        validate(raw, rows)


def test_unneeded_or_duplicate_retirements_are_rejected():
    rows, raw = prepared()
    retire(raw)
    raw["fact_disposition"]["retired_facts"] *= 2
    with pytest.raises(DispositionError, match="disposition_mismatch"):
        validate(raw, rows)


def test_terminal_barrier_and_legacy_without_scope_do_not_invent_task_fact_authority():
    rows, raw = prepared()
    raw["todos"] = []
    validate(raw, rows)
    legacy = declaration()
    del legacy["checkpoint"]["phase_state"]
    old = sources() + receipt("legacy", legacy["todos"], legacy["checkpoint"])
    assert basis(old) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", [False, True])
@pytest.mark.parametrize("native", [False, True])
async def test_real_transaction_rejects_silent_loss_then_restores_declared_disposition(tmp_path, monkeypatch, retirement, native):
    import json
    from engine.abort import AbortController
    from evals.wsc_flash_compact_chain import native_store
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from session.compression_source import compression_messages
    from session.record_transcript import record_transcript_sync, load_transcript
    from session.transcript_blobs import resolve_transcript_rows
    from synaptic.todo_snapshot import latest_todo_snapshot
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    rows, initial = prepared()
    store = native_store(rows)
    source = lambda: compression_messages(store, WorkingSnapshot())
    prefix_rows = deepcopy(source())
    tools = ToolRegistry(cwd=str(tmp_path))
    tools.register(TodoWriteTool(cwd=str(tmp_path)))
    path, known, sent = tmp_path / "facts.jsonl", set(), []
    def persist():
        record_transcript_sync(store.items, session_id="facts", path=path, known_ids=known)
    persist()
    prefix = path.read_bytes()
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, schemas, abort):
            candidate = deepcopy(initial)
            # First valid-looking declaration keeps source IDs but drops the fact.
            if not sent:
                retire(candidate)
                del candidate["fact_disposition"]
                assert "fact_disposition" in schemas[0]["input_schema"]["properties"]
            else:
                error = json.loads(messages[-1]["content"][0]["content"])
                assert error["error"] == "handoff_task_fact_disposition_missing"
                assert source() == prefix_rows and path.read_bytes() == prefix
                if retirement: retire(candidate)
                cp = candidate["checkpoint"]
                cp["context_message_ids"].append("next")
                cp["phase_state"]["current_phase_id"] = "report"
                cp["phase_state"]["active_context_message_ids"] = ["plan", "next"]
                cp["phase_state"]["phases"].append({"id": "report", "name": "汇报",
                                                     "source_message_ids": ["next"]})
            sent.append(deepcopy(messages))
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"new-{len(sent)}", "TodoWrite", candidate))
    async def declare(captured):
        # An explicitly scoped prior state carries the contract even without a flag.
        return await generate(Model(), [{"role": "user", "content": "继续"}], captured,
                              TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    result = await commit(source=source, generate=declare, store=store, tools=tools,
                          abort=AbortController(), persist=persist)
    assert result["call_id"] == "new-2" and len(sent) == 2
    assert path.read_bytes().startswith(prefix) and source()[:len(prefix_rows)] == prefix_rows
    restored = resolve_transcript_rows(load_transcript(path), path)
    facts = basis(restored)
    if retirement:
        assert facts is None
        assert "fact_disposition" in str(restored)
    else:
        assert facts["task_facts"] == [{"field": "constraints", "quote": DURABLE}]
    cp = latest_todo_snapshot(restored).checkpoint
    assert bool(any(f.get("quote") == DURABLE for f in cp["constraints"])) is (not retirement)
    assert cp["phase_state"]["current_phase_id"] == "report"
    from memory.runtime import force_compact, project_for_model
    from memory import wsc_projection
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    wsc_projection._STATE.clear()
    full = restored + [{"id": f"archive-{i}", "role": "assistant", "content": "执行记录" + "x" * 1000}
                       for i in range(35)]
    working = WorkingSnapshot(session_id="fact-" + str(native))
    emitted = force_compact(full, working, cwd=tmp_path)
    assert working.compact_cursor > 0
    head = emitted[0]["content"]
    assert (DURABLE in head) is (not retirement)
    assert DESIGN not in head and "汇报" in head
    full.append({"id": "append", "role": "assistant", "content": "新增执行事实"})
    assert project_for_model(full, working, cwd=tmp_path)[0]["content"] == head
    assert path.read_bytes().startswith(prefix)
