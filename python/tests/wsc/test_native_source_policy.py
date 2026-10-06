import json

import pytest

from memory import working
from memory.working import WorkingSnapshot, CompactCheckpoint
from memory.wsc_source_layout import APPEND, LEGACY
from memory.wsc_source_policy import configure_source, hydrate_source


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", "0")
    monkeypatch.setenv("XEYO_WSC", "1")
    return tmp_path


@pytest.mark.parametrize("switch", ["0", "1"])
@pytest.mark.parametrize("layout", [LEGACY, APPEND])
def test_real_engine_startup_obeys_source_policy(isolated, monkeypatch, switch, layout):
    from engine.query_engine import QueryEngine
    from tools.tool_registry import ToolRegistry
    snapshot = WorkingSnapshot(session_id="policy-real-engine", compression_source_layout=layout,
        compact_cursor=12, c1_frozen_until=12, c2_summary_text="head", agent_mode="ask",
        compact_checkpoint=CompactCheckpoint(anchor_cursor=12, anchor_frozen_until=12),
        todos=[{"content":"continue", "status":"pending"}])
    working.flush(snapshot.session_id, snapshot)
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", switch)
    engine = QueryEngine(dict(cwd=str(isolated), session_id=snapshot.session_id,
                              tools=ToolRegistry(), model_client=object(), runtime_checkpoint=False))
    resumed = engine._session.working
    expected = layout if switch == "1" else LEGACY
    assert resumed.compression_source_layout == expected
    assert resumed.compact_cursor == (12 if layout == expected else 0)
    assert resumed.todos == snapshot.todos and resumed.agent_mode == "ask"
    assert resumed.compression_source_transition_enabled is None


@pytest.mark.parametrize("carrier", ["legacy", "unvalidated"])
def test_unsupported_carrier_resets_coordinates_preserving_state(isolated, monkeypatch, carrier):
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", "1")
    state = WorkingSnapshot(session_id="carrier-policy", compression_source_layout=APPEND,
        compact_cursor=12, c2_summary_text="old", c2_gap_shots=20, agent_mode="ask",
        todos=[{"content":"continue", "status":"pending"}])
    assert not configure_source(state, cwd=str(isolated), carrier=carrier)
    assert state.compression_source_layout == LEGACY and state.compact_cursor == 0
    assert state.c2_summary_text == "" and state.c2_gap_shots == 0
    assert state.todos[0]["content"] == "continue" and state.agent_mode == "ask"


def test_runtime_switch_off_and_unknown_saved_source_are_safe(isolated, monkeypatch):
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", "1")
    state = WorkingSnapshot(session_id="live-source", compression_source_layout=APPEND, compact_cursor=12)
    assert configure_source(state, cwd=str(isolated), carrier="notice_fragment")
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", "0")
    assert not configure_source(state, cwd=str(isolated), carrier="notice_fragment")
    assert state.compression_source_layout == LEGACY and state.compact_cursor == 0
    working.flush(state.session_id, state)
    path = working.path_for(state.session_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(compression_source_layout="future-source", compact_cursor=99, agent_mode="ask")
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", "1")
    resumed = hydrate_source(state.session_id)
    assert resumed.compression_source_layout == LEGACY and resumed.compact_cursor == 0
    assert resumed.agent_mode == "ask"


def test_observational_hydrate_preserves_stored_layout_without_enabling(isolated):
    state = WorkingSnapshot(session_id="observation", compression_source_layout=APPEND, compact_cursor=12)
    working.flush(state.session_id, state)
    before = working.path_for(state.session_id).read_bytes()
    observed = working.hydrate(state.session_id, source_layout=None)
    assert observed.compression_source_layout == APPEND and observed.compact_cursor == 12
    assert observed.compression_source_transition_enabled is None
    assert working.path_for(state.session_id).read_bytes() == before


def test_disabled_wsc_does_not_activate_append_policy(isolated, monkeypatch):
    state = WorkingSnapshot(session_id="disabled-wsc", compression_source_layout=APPEND, compact_cursor=12)
    working.flush(state.session_id, state)
    monkeypatch.setenv("XEYO_WSC_APPEND_SOURCE", "1")
    monkeypatch.setenv("XEYO_WSC", "0")
    resumed = hydrate_source(state.session_id)
    assert resumed.compression_source_layout == LEGACY and resumed.compact_cursor == 0
