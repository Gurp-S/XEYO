import importlib
from pathlib import Path

from evals.wsc_state_lifecycle import StateLifecycle
from evals.wsc_source_transition import transition_to_append
from evals.wsc_append_state import install_note_exclusion
from memory.working import WorkingSnapshot
from memory.runtime import c2_cut_index
from session.message_store import MessageStore
from msgtypes.message import user_message, system_note, assistant_text_message
from tests.wsc._fixtures import synth_session, msg_asst_text


def test_legacy_numeric_cursor_does_not_identify_ordinary_boundary_after_note_revision():
    items = [user_message("request"), system_note("active=1", key="state", fp="old"),
             assistant_text_message("prior"), system_note("active=0", key="state", fp="new"),
             assistant_text_message("latest")]
    old = MessageStore(items[:3]).as_api_messages()
    current = MessageStore(items).as_api_messages()
    assert sum(not row.get("note_key") for row in old[:2]) == 1
    assert sum(not row.get("note_key") for row in current[:2]) == 2
    # Thus mapping cursor=2 using the current latest-note view can absorb 'prior',
    # even though that message was outside the original compacted prefix.
    assert "prior" not in str(old[:2])
    assert "prior" in str(current[:2])


def test_source_transition_preserves_pending_state_and_noncompression_state():
    run = StateLifecycle(reuse_equal_state=False, persist="late")
    raw = [{"role": "user", "content": "request"},
           {"role": "user", "content": "active=1", "note_key": "state", "note_fp": "old"}]
    run.finish(run.prepare(raw))
    working = WorkingSnapshot(compact_cursor=2, c1_frozen_until=2, c2_summary_text="legacy",
                              todos=[{"content": "work", "status": "pending"}], agent_mode="ask", c2_gap_shots=17)
    pending = list(run.pending)
    original = list(run.store.items)
    assert transition_to_append(run, working)
    assert run.store.items == original
    assert run.pending == pending
    assert run.current["state"].content == "active=1"
    assert working.compact_cursor == working.c1_frozen_until == 0
    assert working.compact_checkpoint is None
    assert working.agent_mode == "ask" and working.todos[0]["content"] == "work"
    assert working.c2_gap_shots == 0
    working.compact_cursor = 4
    assert not transition_to_append(run, working)
    assert working.compact_cursor == 4


def test_transition_trigger_requires_confirmed_frozen_prefix_change():
    from types import SimpleNamespace
    from memory.wsc_head_store import region_seal
    from evals.wsc_source_transition import invalid_frozen_source

    rows = [{"role": "user", "content": "request"}, {"role": "user", "content": "state",
            "note_key": "world_state", "note_fp": "state"}]
    cached = SimpleNamespace(region_end=2, source_seal=region_seal(rows, 2))
    assert not invalid_frozen_source(None, rows)
    assert not invalid_frozen_source(cached, rows + [{"role": "assistant", "content": "response"}])
    assert invalid_frozen_source(cached, [rows[0], {**rows[1], "content": "changed"}])


def test_retained_ledger_does_not_suppress_absorbed_or_changed_state():
    run = StateLifecycle(reuse_equal_state=False, persist="late", storage="append")
    raw = [{"role": "user", "content": "request"},
           {"role": "user", "content": "active=1", "note_key": "world_state", "note_fp": "old"}]
    run.finish(run.prepare(raw))
    source = run.prepare(raw + [msg_asst_text("response")])
    run.finish(source)  # A source-layout migration does not clear state ledger.
    assert run.injected == 1
    run.finish([{"role": "assistant", "content": "compressed"}])
    assert run.injected == 2  # Fingerprint in ledger alone cannot prove visibility.
    changed = raw + [msg_asst_text("response"),
                     {**raw[-1], "content": "active=0", "note_fp": "new"}]
    result = run.finish(run.prepare(changed))
    assert [row["content"] for row in result if row.get("note_key")] == ["active=0"]


def test_real_wsc_transition_rebuild_keeps_published_cold_file(monkeypatch, tmp_path):
    wp = importlib.import_module("memory.wsc_projection")
    for name, value in {"XEYO_WSC": "1", "XEYO_WSC_FROZEN_HEAD": "1",
                        "XEYO_WSC_CADENCE_ABSORB": "0", "XEYO_WSC_HEAD_STORE": "0",
                        "XEYO_WSC_OFFLINE": "1"}.items():
        monkeypatch.setenv(name, value)
    wp._STATE.clear()
    run = StateLifecycle(reuse_equal_state=False, persist="late")
    raw = synth_session(turns=26) + [{"role": "user", "content": "active=1",
                                   "note_key": "world_state", "note_fp": "old"}]
    working = WorkingSnapshot(session_id="source-transition-test")
    try:
        source = run.prepare(raw)
        from session.hydrate import message_from_row
        # Give the legacy head an actual note inside its frozen source region.
        run.store.insert(1, message_from_row(raw[-1]))
        source = run.store.as_api_messages()
        working.compact_cursor = c2_cut_index(source, None)
        out = wp.project_c2_messages(source, working, cwd=str(tmp_path))
        run.finish(out, fold=True)
        old = wp._STATE[wp._state_key(working.session_id, str(tmp_path))]
        old_path = Path(old.view_path)
        old_bytes = old_path.read_bytes()
        assert old.region_end > 1
        changed_raw = raw + [msg_asst_text("response"),
                             {**raw[-1], "content": "active=0", "note_fp": "new"}]
        changed_source = run.prepare(changed_raw)
        from evals.wsc_source_transition import invalid_frozen_source
        assert invalid_frozen_source(old, changed_source)
        transition_to_append(run, working)
        wp._STATE.clear()
        source = run.store.as_api_messages()
        working.compact_cursor = c2_cut_index(source, None)
        with install_note_exclusion():
            out = wp.project_c2_messages(source, working, cwd=str(tmp_path))
        current = wp._STATE[wp._state_key(working.session_id, str(tmp_path))]
        assert current.view_path != str(old_path)
        assert old_path.read_bytes() == old_bytes
        delivered = run.finish(out)  # A layout transition alone keeps state ledger.
        assert delivered[-1]["content"] == "active=0"
        assert "active=1" not in current.head
    finally:
        wp._STATE.clear()
