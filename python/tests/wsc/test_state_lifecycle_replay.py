from evals.wsc_extension_economics_ab import canonical_projection
from evals.wsc_state_lifecycle import StateLifecycle


def history():
    return [{"role": "user", "content": "request", "id": "request"},
            {"role": "user", "content": "active=1", "note_key": "world_state",
             "note_fp": "state", "id": "note"}]


def test_early_persistence_preserves_the_emitted_prefix_before_response():
    raw = history()
    for persist in ("early", "late"):
        run = StateLifecycle(reuse_equal_state=False, persist=persist, dedup="visible")
        first = run.finish(run.prepare(raw))
        second = run.prepare(raw + [{"role": "assistant", "content": "response", "id": "response"}])
        prefix_equal = canonical_projection(second[:len(first)], "openai") == canonical_projection(first, "openai")
        assert prefix_equal is (persist == "early")


def test_native_early_persistence_keeps_legacy_order_until_source_transition():
    from memory.working import WorkingSnapshot
    from memory.wsc_source_layout import APPEND, LEGACY

    raw = history()
    for layout in (LEGACY, APPEND):
        working = WorkingSnapshot(session_id="native-early-order")
        working.compression_source_layout = layout
        run = StateLifecycle(reuse_equal_state=False, persist="native-early",
                             storage="append", native_working=working)
        first = run.finish(run.prepare(raw))
        second = run.prepare(raw + [{"role": "assistant", "content": "response", "id": "response"}])
        assert [row["content"] for row in second] == (
            ["request", "active=1", "response"] if layout == APPEND else
            ["request", "response", "active=1"])
        if layout == APPEND:
            assert canonical_projection(second[:len(first)], "openai") == canonical_projection(first, "openai")


def test_cleared_ledger_reinjects_a_state_that_is_still_actually_visible():
    raw = history()
    counts = []
    for policy in ("ledger", "visible"):
        run = StateLifecycle(reuse_equal_state=False, persist="late", dedup=policy)
        run.finish(run.prepare(raw))
        raw2 = raw + [{"role": "assistant", "content": "response", "id": "response"}]
        run.finish(run.prepare(raw2), fold=True)
        raw3 = raw2 + [{"role": "assistant", "content": "more", "id": "more"}]
        run.finish(run.prepare(raw3))
        counts.append(run.injected)
    assert counts == [2, 1]


def test_disappearing_state_does_not_reappear_from_pending_injection():
    run = StateLifecycle(reuse_equal_state=False, persist="late")
    raw = history()
    run.finish(run.prepare(raw))
    retracted = [raw[0], {**raw[1], "note_retracted": True}, {"role": "assistant", "content": "response", "id": "response"}]
    projected = run.prepare(retracted)
    assert not any(row.get("note_key") for row in run.finish(projected))


def test_detached_state_keeps_ordinary_history_and_delivers_current_value():
    run = StateLifecycle(reuse_equal_state=False, persist="late", storage="detached")
    raw = history()
    first = run.prepare(raw)
    assert [row["content"] for row in first] == ["request"]
    assert run.finish(first)[-1]["content"] == "active=1"
    raw2 = raw + [{"role": "assistant", "content": "response", "id": "response"},
                  {**raw[1], "id": "new-state", "content": "active=0", "note_fp": "new"}]
    second = run.prepare(raw2)
    assert [row["content"] for row in second] == ["request", "response"]
    assert run.finish(second)[-1]["content"] == "active=0"


def test_changing_state_detaches_once_but_stable_state_stays_in_history():
    run = StateLifecycle(reuse_equal_state=False, persist="late", storage="changing")
    raw = history()
    run.finish(run.prepare(raw))
    raw2 = raw + [{"role": "assistant", "content": "response", "id": "response"}]
    stable = run.prepare(raw2)
    assert any(row.get("note_key") == "world_state" for row in stable)
    assert not run.detached_keys
    run.finish(stable)
    raw3 = raw2 + [{**raw[1], "id": "new-state", "content": "active=0", "note_fp": "new"}]
    changed = run.prepare(raw3)
    assert not any(row.get("note_key") for row in changed)
    assert run.finish(changed)[-1]["content"] == "active=0"
    assert run.detached_keys == {"world_state"}
    raw4 = raw3 + [{"role": "assistant", "content": "more", "id": "more"}]
    next_input = run.prepare(raw4)
    assert [row["content"] for row in next_input] == ["request", "response", "more"]


def test_detachment_does_not_overwrite_prior_cold_generation(monkeypatch, tmp_path):
    import importlib
    from pathlib import Path
    from memory.runtime import c2_cut_index
    from memory.working import WorkingSnapshot
    from tests.wsc._fixtures import synth_session, msg_asst_text, msg_asst_use, msg_tool

    wp = importlib.import_module("memory.wsc_projection")
    for name, value in {"XEYO_WSC": "1", "XEYO_WSC_FROZEN_HEAD": "1",
                        "XEYO_WSC_CADENCE_ABSORB": "0", "XEYO_WSC_HEAD_STORE": "0",
                        "XEYO_WSC_OFFLINE": "1"}.items():
        monkeypatch.setenv(name, value)
    wp._STATE.clear()
    run = StateLifecycle(reuse_equal_state=False, persist="late", storage="changing")
    raw = synth_session(turns=26) + [history()[1]]
    working = WorkingSnapshot(session_id="detached-state-cold-history")

    def emit(rows, *, fold=False):
        source = run.prepare(rows)
        if fold:
            working.compact_cursor = c2_cut_index(source, None)
        out = wp.project_c2_messages(source, working, cwd=str(tmp_path))
        assert out is not None
        return run.finish(out, fold=fold), source

    try:
        emit(raw, fold=True)
        raw2 = raw + [msg_asst_text("response")]
        emit(raw2)
        more = []
        for i in range(4):
            uid = f"detach-{i}"
            more += [msg_asst_use(uid, "Read", {"file_path": "src/login.py"}),
                     msg_tool(uid, "Read", "retained file evidence " * 100)]
        raw3 = raw2 + more
        _, source = emit(raw3, fold=True)
        live = wp._STATE[wp._state_key(working.session_id, str(tmp_path))]
        note_index = next(i for i, row in enumerate(source) if row.get("note_key"))
        assert live.region_end > note_index
        prior = Path(live.view_path)
        original_bytes = prior.read_bytes()
        changed_note = {**history()[1], "id": "changed-state", "content": "active=0", "note_fp": "changed"}
        final, detached_source = emit(raw3 + [changed_note, msg_asst_text("after state update")])
        assert not any(row.get("note_key") for row in detached_source)
        assert final[-1]["content"] == "active=0"
        assert prior.read_bytes() == original_bytes
        assert wp._STATE[wp._state_key(working.session_id, str(tmp_path))].view_path != str(prior)
    finally:
        wp._STATE.clear()
