import json

import pytest

from evals.wsc_source_contract import (
    LEGACY, APPEND, source_messages,
)
from memory import working, wsc_head_store
from memory.working import WorkingSnapshot, CompactCheckpoint
from session.message_store import MessageStore
from msgtypes.message import user_message, system_note, assistant_text_message


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    return tmp_path


@pytest.mark.parametrize("layout", [LEGACY, APPEND])
def test_real_working_flush_hydrate_keeps_source_and_checkpoint(isolated, layout):
    state = WorkingSnapshot(session_id="source-contract", compact_cursor=4, c1_frozen_until=4,
                            compact_checkpoint=CompactCheckpoint(anchor_cursor=4, anchor_frozen_until=4),
                            agent_mode="ask", todos=[{"content": "task", "status": "pending"}])
    state.compression_source_layout = layout
    working.flush(state.session_id, state)
    resumed = working.hydrate(state.session_id, source_layout=layout)
    payload = json.loads(working.path_for(state.session_id).read_text(encoding="utf-8"))
    assert payload.get("compression_source_layout", LEGACY) == layout
    assert resumed.compression_source_layout == layout
    assert resumed.compact_cursor == resumed.c1_frozen_until == 4
    assert resumed.compact_checkpoint.anchor_cursor == 4
    assert not resumed.compression_source_rebuilt
    assert resumed.agent_mode == "ask" and resumed.todos == state.todos


@pytest.mark.parametrize("old,new", [(LEGACY, APPEND), (APPEND, LEGACY)])
def test_source_change_resets_all_checkpoint_coordinates_but_keeps_user_state(isolated, old, new):
    state = WorkingSnapshot(session_id="switch-contract", compact_cursor=100, c1_frozen_until=100,
                            c2_summary_text="old summary", agent_mode="plan", c2_gap_shots=17,
                            compact_checkpoint=CompactCheckpoint(anchor_cursor=120, anchor_frozen_until=120))
    state.compression_source_layout = old
    working.flush(state.session_id, state)
    resumed = working.hydrate(state.session_id, source_layout=new)
    assert resumed.compact_cursor == resumed.c1_frozen_until == 0
    assert resumed.compact_checkpoint is None
    assert resumed.c2_summary_text == ""
    assert resumed.compression_source_rebuilt
    assert resumed.agent_mode == "plan"
    working.flush(state.session_id, resumed)
    again = working.hydrate(state.session_id, source_layout=new)
    assert again.compression_source_layout == new
    assert not again.compression_source_rebuilt


def test_unknown_layout_cannot_reuse_numeric_anchors(isolated):
    path = working.path_for("unknown-source")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"compression_source_layout": "future-layout", "compact_cursor": 99,
                               "compact_checkpoint": {"anchor_cursor": 120}, "agent_mode": "ask"}), encoding="utf-8")
    state = working.hydrate("unknown-source", source_layout=APPEND)
    assert state.compact_cursor == 0 and state.compact_checkpoint is None
    assert state.agent_mode == "ask"
    assert state.compression_source_rebuilt


def test_head_seal_rejects_other_layout_even_for_identical_source_bytes(isolated):
    rows = [{"role": "user", "content": "same request"}, {"role": "assistant", "content": "same result"}]
    def save(layout):
        wsc_head_store.save("layout-head", text="head", cwd=str(isolated), cursor=2,
                            region_end=2, messages=rows, source_layout=layout)
    def load(layout):
        return wsc_head_store.load("layout-head", cwd=str(isolated), cursor=2, messages=rows, source_layout=layout)
    save(LEGACY)
    assert load(LEGACY).text == "head"
    assert load(APPEND) is None
    save(APPEND)
    assert load(APPEND).text == "head"
    assert load(LEGACY) is None


def test_compression_source_is_separate_from_api_export_view():
    store = MessageStore([user_message("request"), system_note("old", key="state", fp="old"),
                          assistant_text_message("response"), system_note("new", key="state", fp="new")])
    api = store.as_api_messages()
    raw = list(store.items)
    source = source_messages(store, APPEND)
    assert [r["content"] for r in source if r.get("note_key")] == ["old", "new"]
    assert [r["content"] for r in source_messages(store, LEGACY) if r.get("note_key")] == ["new"]
    assert store.as_api_messages() == api
    assert store.items == raw


@pytest.mark.parametrize("layout", [LEGACY, APPEND])
@pytest.mark.parametrize("reused", [False, True])
def test_native_manual_compaction_and_restart_preserve_same_source(isolated, monkeypatch, layout, reused):
    from contextlib import nullcontext
    from pathlib import Path
    import importlib
    from evals.wsc_append_state import install_note_exclusion
    from session.hydrate import message_from_row
    from memory.runtime import force_compact, project_for_model
    from evals.wsc_source_reader import SourceReader
    from tests.wsc._fixtures import synth_session

    wp = importlib.import_module("memory.wsc_projection")
    for name, value in {"XEYO_WSC": "1", "XEYO_WSC_FROZEN_HEAD": "1",
                        "XEYO_WSC_CADENCE_ABSORB": "0", "XEYO_WSC_OFFLINE": "1",
                        "XEYO_L5": "project"}.items():
        monkeypatch.setenv(name, value)
    rows = synth_session(turns=26)
    items = [message_from_row(row) for row in rows]
    items.insert(1, system_note("old state", key="state", fp="old"))
    items.append(system_note("current state", key="state", fp="new"))
    store = MessageStore(items)
    get_source = SourceReader().read if reused else source_messages
    state = WorkingSnapshot(session_id="contract-native-" + layout)
    state.compression_source_layout = layout
    api = store.as_api_messages()
    wp._STATE.clear()
    try:
        with (install_note_exclusion() if layout == APPEND else nullcontext()):
            # Same getter feeds real manual and real automatic projection APIs.
            manual_source = get_source(store, layout)
            force_compact(manual_source, state, cwd=str(isolated))
            before = project_for_model(get_source(store, layout), state,
                                       include_memory_index=False, cwd=str(isolated))
            assert before and state.compact_cursor > 0
            cached = wp._STATE[wp._state_key(state.session_id, str(isolated))]
            cold_path = Path(cached.view_path)
            cold_bytes = cold_path.read_bytes()
            working.flush(state.session_id, state)
            wp._STATE.clear()
            resumed = working.hydrate(state.session_id, source_layout=layout)
            after = project_for_model(get_source(store, resumed.compression_source_layout), resumed,
                                      include_memory_index=False, cwd=str(isolated))
            assert after == before
            assert cold_path.read_bytes() == cold_bytes
            assert resumed.compact_cursor == state.compact_cursor
            assert store.as_api_messages() == api
    finally:
        wp._STATE.clear()
