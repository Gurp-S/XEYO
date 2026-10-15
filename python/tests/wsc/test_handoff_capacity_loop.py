"""Capacity handoff uses real query loop, tools and transcript persistence."""
from copy import deepcopy

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("schema_bytes", [300000, 355000, 500000])
@pytest.mark.parametrize("native", [False, True])
async def test_capacity_generates_before_fold_and_accounts_separate_request(monkeypatch, tmp_path, valid, existing, schema_bytes, native, recovered=False, unconsumed=False, missing_generation=False):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / "usage"))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / "spill"))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    monkeypatch.setattr("memory.wsc_projection._STATE", {})
    monkeypatch.setattr("engine.first_sniff.maybe_first_sniff_text", lambda **kwargs: "")
    store = MessageStore([Message(role="user", id="spec", content="当前规范：写报告并引用实际验收")])
    if recovered:
        from tests.wsc.test_handoff_validation import recovered_fixture
        from session.hydrate import messages_from_rows
        recovery_rows, _state = recovered_fixture()
        for message in messages_from_rows(recovery_rows[1:]):
            store.append(message)
    for i in range(35): store.append(Message(role="assistant", content="背景记录 " + "x" * 2000))
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    if existing:
        prior = ToolUse("prior-state", "TodoWrite", {
            "todos": [{"id": "report", "content": "写报告", "activeForm": "写报告", "status": "pending"}],
            "checkpoint": {"objective": "完成当前报告", "context_message_ids": ["spec"]}})
        store.append(assistant_text_message("", [prior]))
        result = await registry.run(prior, AbortController())
        store.append(tool_result_message(prior.id, prior.name, result.content, execution=result.execution_metadata()))
        store.append(Message(role="user", id="supplement", content="补充规范：报告绑定最近实际成功回执"))
    unread = 'UNCONSUMED_RESULT:' + ('receipt line\n' * 1100)
    if unconsumed:
        store.append(assistant_text_message('', [ToolUse('unread-result', 'Read', {'file_path': 'receipt.txt'})]))
        store.append(tool_result_message('unread-result', 'Read', unread,
            execution={'complete': True, 'status': 'ok'}))
    oversized = schema_bytes == 500000
    schema_size = schema_bytes
    class Heavy:
        name = "Heavy"
        @staticmethod
        def is_read_only(): return True
        @staticmethod
        def is_concurrency_safe(): return True
        def schema(self): return {"name": self.name, "description": "x" * schema_size, "input_schema": {"type": "object"}}
    registry.register(Heavy())
    calls = []
    class Handoff:
        last_usage = None
        async def stream(self, messages, tools, abort):
            calls.append("handoff")
            assert [tool["name"] for tool in tools] == ["TodoWrite", "HandoffSource", "HandoffCatalog"]
            assert "spec" in messages[-1]["content"]
            self.last_usage = {"prompt_tokens": 100, "completion_tokens": 20}
            from tests.wsc._fixtures import declared_report_phase
            yield ModelChunk(kind="tool_use", tool_use=ToolUse("handoff", "TodoWrite", {
                "todos": [{"id": "report", "content": "写报告", "activeForm": "写报告", "status": "pending"}],
                "checkpoint": {"objective": "完成当前报告", "context_message_ids": (["spec", "supplement"] if existing else ["spec"]) if valid else ["invented"],
                               "phase_state": declared_report_phase("spec" if valid else "invented"),
                               **({"verification_call_ids": ["verify"]} if recovered else {})}}))
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens):
            assert max_tokens == 2048
            return Handoff()
        async def stream(self, messages, tools, abort):
            calls.append("main")
            assert "当前规范：写报告并引用实际验收" in str(messages)
            assert "完成当前报告" in str(messages)
            if unconsumed:
                # The task model has not consumed this receipt merely because
                # the isolated handoff committed and history was folded.
                import json
                assert json.dumps(unread, ensure_ascii=False)[1:-1] in json.dumps(messages, ensure_ascii=False)
                assert 'unread-result' in str(messages)
            if recovered:
                assert "verify" in str(messages)
                assert "failed" in str(messages)
            self.last_usage = {"prompt_tokens": 200, "completion_tokens": 10}
            yield ModelChunk(kind="text_delta", text="当前任务状态已观察")
    path = tmp_path / "transcript.jsonl"
    known = set()
    def persist(): record_transcript_sync(store.items, session_id="fixture", path=path, known_ids=known)
    persist()
    prefix = path.read_bytes()
    original = deepcopy(store.items)
    working = WorkingSnapshot(session_id="capacity-handoff")
    if missing_generation:
        from memory.runtime import force_compact
        from memory import wsc_projection, wsc_head_store
        from session.compression_source import compression_messages
        force_compact(compression_messages(store, working), working, cwd=tmp_path)
        assert working.compact_cursor > 0
        wsc_head_store.path_for(working.session_id).unlink()
        wsc_projection._STATE.clear()
    budget = BudgetTracker(max_turns=4)
    events = [event async for event in query_loop(store=store, model=Model(), tools=registry,
        prompt=PromptAssembler(), system_prompt="fixture", abort=AbortController(), budget=budget,
        working=working, persist_handoff=persist)]
    assert path.read_bytes().startswith(prefix)
    assert store.items[:len(original)] == original
    if valid:
        assert calls == (["handoff"] if oversized else ["handoff", "main"])
        assert working.compact_cursor > 0
        assert working.wsc_timing_state["last_handoff_commit"]["call_id"] == "handoff"
        assert working.wsc_timing_state["last_handoff_commit"]["semantic_status"] == "SEMANTIC_UNVERIFIED"
        if recovered:
            admission = working.wsc_timing_state["last_request_admission"]
            assert admission["automatic_attempts"] == 1
            assert admission["model_requested"] is False
            assert admission["before"]["emitted_tokens"] >= 85000
            assert admission["cursor_advanced"] is True
        assert budget.turn_count == 2 and budget.used_tokens == (120 if oversized else 330)
        if oversized:
            assert any(getattr(event, "reason", "").startswith("context_capacity_exceeded:") for event in events)
            assert working.wsc_timing_state['last_request_admission']['after']['emitted_tokens'] >= Model.context_limit
            durable = path.read_bytes()
            if unconsumed:
                from session.compression_source import compression_messages
                from memory.wsc_execution_boundary import protect
                source = compression_messages(store, working)
                assert working.compact_cursor <= protect(source, len(source))
            from memory.working import flush, hydrate
            from session.hydrate import messages_from_rows
            from session.record_transcript import load_transcript
            from memory.wsc_projection import _STATE
            flush(working.session_id, working)
            _STATE.clear()
            working = hydrate(working.session_id, source_layout=working.compression_source_layout)
            store = MessageStore(messages_from_rows(load_transcript(path)))
            # A later submit with smaller schemas resumes from the committed
            # state; no duplicate handoff or lost source is required.
            schema_size = 2000
            registry = ToolRegistry(cwd=str(tmp_path))
            registry.register(TodoWriteTool(cwd=str(tmp_path)))
            registry.register(Heavy())
            resumed = BudgetTracker(max_turns=4)
            resumed_events = [event async for event in query_loop(store=store, model=Model(), tools=registry,
                prompt=PromptAssembler(), system_prompt="fixture", abort=AbortController(), budget=resumed,
                working=working, persist_handoff=persist)]
            assert calls == ['handoff', 'main'] and resumed.used_tokens == 210, [getattr(e, 'reason', '') for e in resumed_events]
            assert path.read_bytes() == durable
        elif schema_bytes == 355000:
            # 85% starts a fold; it is not a post-fold target or hard stop.
            measured = working.wsc_timing_state['last_request_admission']['after']['emitted_tokens']
            assert 85000 <= measured < Model.context_limit
    else:
        assert calls == ["handoff"] and working.compact_cursor == 0
        assert path.read_bytes() == prefix and store.items == original
        assert any(getattr(event, "reason", "") == "handoff_context_source_not_unique" for event in events)
        assert budget.used_tokens == 120


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_recovered_result_crosses_real_capacity_handoff_entry(monkeypatch, tmp_path, native):
    await test_capacity_generates_before_fold_and_accounts_separate_request(
        monkeypatch, tmp_path, valid=True, existing=False, schema_bytes=300000,
        native=native, recovered=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
async def test_successful_handoff_then_capacity_stop_preserves_unconsumed_result_on_restart(monkeypatch, tmp_path, native):
    await test_capacity_generates_before_fold_and_accounts_separate_request(
        monkeypatch, tmp_path, valid=True, existing=False, schema_bytes=500000,
        native=native, unconsumed=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('schema_bytes', [300000, 500000])
async def test_missing_generation_full_replay_enters_capacity_preparation(monkeypatch, tmp_path, schema_bytes):
    await test_capacity_generates_before_fold_and_accounts_separate_request(
        monkeypatch, tmp_path, valid=True, existing=False, schema_bytes=schema_bytes,
        native=True, missing_generation=True)
