"""Native query-loop assembly; conditional migration still uses an isolated hook."""
import copy
import importlib
import json
from contextlib import nullcontext
from pathlib import Path

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_carrier", ["notice_fragment", "system_channel", "env_channel"])
@pytest.mark.parametrize("conditional,boundary,restarted", [(False, False, False), (True, False, False), (True, True, False), (True, True, True)])
@pytest.mark.parametrize("old_versions", [1, 8])
@pytest.mark.parametrize("memory_mode", ["project", "v61"])
async def test_real_query_loop_append_source_current_state_and_prefix(monkeypatch, tmp_path, mem_switch, conditional, boundary, restarted, old_versions, primary_carrier, memory_mode):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.workspace_context import WorkspaceContext, bind_workspace_context
    from evals.wsc_query_source import QuerySource, ConditionalQuerySource, select_rendered_state
    from evals.wsc_source_contract import APPEND
    from memory.working import WorkingSnapshot
    from memory.runtime import force_compact
    from model.chunks import ModelChunk
    from msgtypes.message import user_message, system_note, tool_result_message, notice_note
    from prompt import inject_store, pre_llm_inject as pre
    from prompt.assembler import PromptAssembler
    from prompt.notice_channel import wrap_notice
    from session.hydrate import message_from_row
    from session.message_store import MessageStore
    from tests.wsc._fixtures import synth_session
    from tools.tool_registry import ToolRegistry
    from extension.reconcile import publish_reconcile_block, reset_reconcile_state

    ql = importlib.import_module("engine.query_loop")
    notes = importlib.import_module("engine.t_now_notes")
    wp = importlib.import_module("memory.wsc_projection")
    for name, value in {"XEYO_HOME": str(tmp_path / "home"),
                        "XEYO_SESSIONS_DIR": str(tmp_path / "sessions"),
                        "XEYO_WSC": "1", "XEYO_WSC_FROZEN_HEAD": "1",
                        "XEYO_WSC_CADENCE_ABSORB": "0", "XEYO_WSC_HEAD_STORE": "1",
                        "XEYO_WSC_OFFLINE": "1", "XEYO_T_NOW_STRATEGY": "notice_fragment",
                        "XEYO_WSC_APPEND_SOURCE": "1",
                        inject_store.FLAG_ENV: "on"}.items():
        monkeypatch.setenv(name, value)
    mem_switch(XEYO_L5=memory_mode)
    # WSC fixture uses legacy user/tool_result blocks; the engine store uses
    # native tool rows. Feed the same facts in its real in-memory shape so the
    # query entry repair does not legitimately insert missing result rows.
    items = []
    for row in synth_session(turns=26):
        content = row.get("content")
        if row.get("role") == "user" and isinstance(content, list) and content[0].get("type") == "tool_result":
            result = content[0]
            items.append(tool_result_message(result["tool_use_id"], row.get("name", ""),
                                             result["content"], is_error=result.get("is_error", False)))
        else:
            items.append(message_from_row(row))
    items.insert(1, system_note("obsolete state", key="world_state", fp="old"))
    for i in range(1, old_versions):
        items.insert(1 + i, system_note(f"retired state {i}", key="world_state", fp=f"old-{i}"))
    # A user quotation of an engine-shaped block must remain an ordinary fact.
    quotation = wrap_notice("user quotation retained", "world_state")
    items.append(user_message(quotation))
    store = MessageStore(items)
    working = WorkingSnapshot(session_id="query-source-native")
    source = ConditionalQuerySource(store, working, str(tmp_path)) if conditional else QuerySource(store, APPEND)
    working.compression_source_layout = source.layout
    if conditional and not boundary:
        # Retain the deliberately late adapter as an ablation of the native boundary.
        from memory import wsc_source_transition as transition
        monkeypatch.setattr(transition, "prepare_compression_source", lambda *args, **kwargs: False)
    native_boundary_transitions = []
    if conditional and boundary:
        from memory import wsc_source_transition as transition
        native_prepare = transition.prepare_compression_source
        def prepare_observed(actual_store, snapshot, **kwargs):
            changed = native_prepare(actual_store, snapshot, **kwargs)
            if changed:
                native_boundary_transitions.append(True)
            return changed
        monkeypatch.setattr(transition, "prepare_compression_source", prepare_observed)
    if not conditional or boundary:
        # Run the engine against the actual store, without source API overrides.
        from session.compression_source import _reader
        native_read = ql.compression_messages
        def read_observed(actual_store, snapshot):
            previous = _reader._cache.get(actual_store)
            rows = native_read(actual_store, snapshot)
            source.reads.append(previous is not None and previous[1] is rows)
            return rows
        monkeypatch.setattr(ql, "compression_messages", read_observed)
    event_text = "reconcile event payload retained exactly once"
    observations = []
    ledger_invalidations = []
    native_invalidate = notes.invalidate_after_compaction

    def invalidate():
        ledger_invalidations.append(len(observations) + 1)
        return native_invalidate()

    monkeypatch.setattr(notes, "invalidate_after_compaction", invalidate)
    class Model:
        async def stream(self, messages, tools, abort):
            observations.append(copy.deepcopy(messages))
            states = [row for row in messages if row.get("note_key") == "world_state"]
            assert len(states) <= 1
            def texts(data):
                if isinstance(data, str):
                    yield data
                elif isinstance(data, list):
                    for element in data:
                        yield from texts(element)
                elif isinstance(data, dict):
                    for key in ("content", "text"):
                        yield from texts(data.get(key))
            body = list(texts(messages))
            # Check continuation facts as well as the injected state marker.
            for fact in ("修复登录超时", "不能修改 API 协议", "v1 兼容",
                         "AssertionError", "修改 proxy 超时配置", "补齐超时回归测试"):
                assert any(fact in text for text in body), fact
            if strategy == "skip" or not value:
                assert not any("output_compaction=" in text for text in body)
            else:
                assert sum(value in text for text in body) == 1
                other = "disabled" if "enabled" in value else "enabled"
                assert not any(f"output_compaction={other}" in text for text in body)
            if strategy != "skip":
                assert sum(text.count(event_text) for text in body) == 1
            assert any(row.get("content") == quotation for row in messages)
            yield ModelChunk(kind="text_delta", text="done")
    inject_store.get_store().clear()
    reset_reconcile_state()
    wp._STATE.clear()
    try:
        with nullcontext(), \
             bind_workspace_context(WorkspaceContext(session_id=working.session_id, cwd=str(tmp_path))):
            force_compact(source.as_api_messages(), working, cwd=str(tmp_path))
            key = wp._state_key(working.session_id, str(tmp_path))
            frozen = wp._STATE[key]
            head = frozen.head
            cold_path = Path(frozen.view_path)
            cold_bytes = cold_path.read_bytes()
            if restarted:
                from memory import working as working_store
                from evals.wsc_source_contract import LEGACY
                working_store.flush(working.session_id, working)
                working = working_store.hydrate(working.session_id)
                source.working = working
                wp._STATE.clear()
                # Valid persisted source alone must not cause migration.
                source.as_api_messages()
                assert source.transitions == 0 and source.layout == LEGACY
            if conditional:
                store.append(notice_note(wrap_notice("changed persisted state", "world_state"),
                                         key="world_state", fp="replacement"))
                assert source.transitions == 0
            per_request_reads = []
            cases = [(primary_carrier, "# Engine state\noutput_compaction=enabled"),
                     (primary_carrier, "# Engine state\noutput_compaction=enabled"),
                     (primary_carrier, "# Engine state\noutput_compaction=disabled"),
                     ("skip", "# Engine state\noutput_compaction=disabled"),
                     (primary_carrier, "# Engine state\noutput_compaction=disabled"),
                     (primary_carrier, "")]
            for strategy, value in cases:
                monkeypatch.setenv("XEYO_T_NOW_STRATEGY", strategy)
                if strategy != "skip":
                    publish_reconcile_block(event_text)
                monkeypatch.setattr(pre, "compact_block", lambda: value)
                start = len(source.reads)
                async for _ in ql.query_loop(store=source if conditional and not boundary else store, model=Model(), tools=ToolRegistry(),
                    prompt=PromptAssembler(), system_prompt="stable facts", abort=AbortController(),
                    budget=BudgetTracker(max_turns=2), working=working, include_memory_index=False):
                    pass
                per_request_reads.append({"reads": len(source.reads) - start,
                                          "reused": sum(source.reads[start:])})
                if conditional and len(per_request_reads) == 1:
                    assert (len(native_boundary_transitions) if boundary else source.transitions) == 1
                    assert working.compression_source_layout == APPEND
                    assert wp._STATE[key].view_path != str(cold_path)
                    head = wp._STATE[key].head
                assert wp._STATE[key].head == head
                assert cold_path.read_bytes() == cold_bytes
            assert len(observations) == 6
            assert any(source.reads), "Native loop should actually reuse a source version"
            assert store.items[1].content == "obsolete state"
            api = store.as_api_messages()
            assert "obsolete state" not in [row.get("content") for row in api]
            assert not any(event_text in item.content for item in store.items if isinstance(item.content, str))
            if boundary:
                assert ledger_invalidations == []
            elif conditional and old_versions == 8:
                assert ledger_invalidations == [1]
            (tmp_path / "native-query-source-observation.json").write_text(json.dumps({
                "requests": 6, "reads": per_request_reads, "head_unchanged": True,
                "cold_bytes_unchanged": True, "current_component_and_events_verified": True,
                "ordinary_quotation_retained": True,
                "continuation_request_constraint_error_and_todo_verified": True,
                "notice_skip_notice_recovery": True,
                "conditional_transition": conditional,
                "loop_uses_original_store": not conditional or boundary,
                "transition_count": len(native_boundary_transitions) if boundary else source.transitions if conditional else 0,
                "old_note_versions": old_versions,
                "transition_at_boundary": boundary,
                "legacy_working_rehydrated": restarted,
                "primary_carrier": primary_carrier,
                "memory_mode": memory_mode,
                "registered_source_policy_used": True,
                "repeated_same_event_delivered_once_each_request": True,
                "event_not_persisted_in_state_notes": True,
                "ledger_invalidations_after_request_assembly": ledger_invalidations,
                "scope": "Native query_loop, injector, source reader, state selection and early transition with fake model and controlled facts; late-transition control alone uses isolated source adapter; no task-score or paid-cost verification",
            }, indent=2), encoding="utf-8")
    finally:
        if conditional:
            source.close()
        wp._STATE.clear()
        inject_store.get_store().clear()
        reset_reconcile_state()


def test_closed_carrier_removes_old_state_even_when_facts_were_generated():
    from evals.wsc_query_source import select_rendered_state
    state = {"role": "user", "content": "old state", "note_key": "world_state"}
    ordinary = {"role": "user", "content": "user fact"}
    current = {"world_state": {"role": "user", "content": "current state"}}
    assert select_rendered_state([ordinary, state], [ordinary, state], current, "skip") == [ordinary]
    with pytest.raises(ValueError, match="carrier not validated"):
        select_rendered_state([ordinary], [ordinary], current, "legacy")
