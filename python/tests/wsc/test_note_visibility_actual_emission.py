from __future__ import annotations

import importlib

import pytest

from msgtypes.message import system_note
from session.hydrate import message_from_row
from session.message_store import MessageStore
from tests.wsc._fixtures import synth_session


def test_real_wsc_absorption_can_exceed_cursor(monkeypatch, tmp_path):
    from memory.working import WorkingSnapshot
    wp = importlib.import_module("memory.wsc_projection")
    monkeypatch.setenv("XEYO_WSC", "1")
    monkeypatch.setenv("XEYO_WSC_FROZEN_HEAD", "1")
    monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "0")
    monkeypatch.setenv("XEYO_WSC_OFFLINE", "1")
    wp._STATE.clear()
    rows = synth_session(turns=26)
    items = [m for row in rows if (m := message_from_row(row)) is not None]
    items.insert(1, system_note("active=1", key="world_state", fp="state"))
    store = MessageStore(items)
    working = WorkingSnapshot(session_id="actual-state-visibility")
    working.compact_cursor = 1
    api = store.as_api_messages()
    try:
        emitted = wp.project_c2_messages(api, working, cwd=str(tmp_path))
        assert emitted is not None
        live = wp._STATE[wp._state_key(working.session_id, str(tmp_path))]
        assert live.region_end > working.compact_cursor
        assert store.note_fingerprints(start=working.compact_cursor) == {("world_state", "state")}
        assert store.note_fingerprints(projected=emitted) == set()
        store.append(system_note("active=1", key="world_state", fp="state"))
        assert store.as_api_messages()[-1]["note_key"] == "world_state"
    finally:
        wp._STATE.clear()


@pytest.mark.asyncio
async def test_query_loop_passes_emitted_visibility_to_injection(monkeypatch, mem_switch):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import assistant_text_message, user_message
    from prompt.assembler import PromptAssembler
    from tools.tool_registry import ToolRegistry

    ql = importlib.import_module("engine.query_loop")
    mem_switch(XEYO_L5="project")
    store = MessageStore([user_message("request"), system_note("active=1", key="world_state", fp="state"), assistant_text_message("prior")])
    working = WorkingSnapshot(session_id="query-note-visibility")
    working.compact_cursor = 1
    observed = []

    def project(messages, snapshot, **kwargs):
        return [{"role": "assistant", "content": "compressed"}, messages[-1]]

    def inject(messages, **kwargs):
        observed.append(kwargs["visible_notes"])
        return messages

    class Model:
        async def stream(self, messages, tools, abort):
            yield ModelChunk(kind="text_delta", text="done")

    monkeypatch.setattr(ql, "project_for_model", project)
    monkeypatch.setattr(ql, "_attach_turn_context", inject)
    async for _ in ql.query_loop(store=store, model=Model(), tools=ToolRegistry(), prompt=PromptAssembler(), system_prompt="facts", abort=AbortController(), budget=BudgetTracker(max_turns=2), working=working):
        pass
    assert observed and observed[0] == frozenset()
