from pathlib import Path
import importlib

from evals.wsc_append_state import install_note_exclusion
from evals.wsc_state_lifecycle import StateLifecycle
from memory.runtime import c2_cut_index
from memory.working import WorkingSnapshot
from tests.wsc._fixtures import synth_session, msg_asst_text, msg_asst_use, msg_tool


def note(value, ident):
    return {"role": "user", "content": f"active={value}", "note_key": "world_state",
            "note_fp": f"value-{value}", "id": ident}


def test_append_source_keeps_positions_and_raw_state_after_retraction():
    run = StateLifecycle(reuse_equal_state=False, persist="late", storage="append")
    raw = [{"role": "user", "content": "request"}, note(1, "first")]
    run.finish(run.prepare(raw))
    stable = run.prepare(raw + [msg_asst_text("response")])
    run.finish(stable)
    changed = run.prepare(raw + [msg_asst_text("response"), note(0, "second")])
    assert changed[:len(stable)] == stable
    delivered = run.finish(changed)
    assert [row["content"] for row in delivered if row.get("note_key")] == ["active=0"]
    retracted = run.prepare([raw[0], {**raw[1], "note_retracted": True},
                             msg_asst_text("response"), {**note(0, "second"), "note_retracted": True}])
    assert retracted[:len(changed)] == changed
    assert not any(row.get("note_key") for row in run.finish(retracted))
    assert any(item.note_key and item.content == "active=1" for item in run.store.items)


def test_note_exclusion_keeps_cold_original_and_ordinary_user_fact():
    from synaptic.project import project
    from synaptic.types import WscParams
    from dataclasses import replace

    raw = [{"role": "user", "content": "Inspect workspace"},
           {**note(1, "first"), "content": "<environment_context>cwd=D:/old</environment_context>"},
           {**note(0, "second"), "content": "<environment_context>cwd=D:/new</environment_context>"},
           {"role": "user", "content": "Keep API protocol v1 compatible"}]
    with install_note_exclusion():
        out = project(raw, region_end=len(raw), params=replace(WscParams(), journal_layout=False,
                                                              freeze_main_chain=False))
    assert "D:/old" not in out.text and "D:/new" not in out.text
    assert "Keep API protocol v1 compatible" in out.text
    assert out.cold.texts[1] == raw[1]["content"]
    assert out.cold.texts[2] == raw[2]["content"]


def test_matched_budget_uses_same_ordinary_tail_and_preserves_protected_facts(tmp_path):
    from evals.wsc_append_budget import matched_pair

    raw = synth_session(turns=10) + [note(1, "first"), msg_asst_text("response"), note(0, "second")]
    pair = matched_pair(raw, cwd=tmp_path, budget=3000)
    assert pair[0]["tail_tokens"] == pair[1]["tail_tokens"]
    assert pair[0]["configured_total_budget"] == pair[1]["configured_total_budget"]
    for result in pair:
        assert result["ordinary_source_count"] == pair[0]["ordinary_source_count"]
        assert result["current_state_count"] == 1
        assert not result["unrecoverable_ordinary"]
        assert not any(result["protected_missing"].values())


def test_post_generation_selection_uses_real_state_renderer(monkeypatch, tmp_path):
    from evals.wsc_append_state import AppendStateStore, select_note_rows
    from prompt import inject_store, pre_llm_inject as pre
    from prompt.notice_channel import wrap_notice
    from prompt.t_now_strategy import STRATEGY_NOTICE_FRAGMENT
    from engine.t_now_notes import persist_pending
    from msgtypes.message import user_message, assistant_text_message

    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv(inject_store.FLAG_ENV, "on")
    store = AppendStateStore([user_message("request")])
    actual = inject_store.get_store()
    actual.clear()
    captured = {}
    original = pre._dedup_round

    def observe(tagged, **kwargs):
        captured.clear()
        captured.update({key: {"role": "user", "content": wrap_notice(text, key)}
                         for key, text in tagged if key == "world_state"})
        return original(tagged, **kwargs)

    monkeypatch.setattr(pre, "_dedup_round", observe)
    sid = "append-live-state-render"
    state = "# Engine state\noutput_compaction=enabled"
    try:
        for value in (state, state, "# Engine state\noutput_compaction=disabled", ""):
            persist_pending(store, session_id=sid, carrier=STRATEGY_NOTICE_FRAGMENT)
            monkeypatch.setattr(pre, "compact_block", lambda: value)
            base = store.as_api_messages()
            out = pre.run_pre_llm_inject(base, pre.InjectContext(
                session_id=sid, cwd="", strategy=STRATEGY_NOTICE_FRAGMENT,
                visible_notes=frozenset(store.note_fingerprints(projected=base))))
            # Only rows created by the actual renderer get internal note identity.
            # Ordinary rows, including user-quoted notices, are never classified.
            marked = [{**row, "note_key": "world_state"}
                      if i >= len(base) and "world_state" in captured and
                         row.get("content") == captured["world_state"]["content"]
                      else row for i, row in enumerate(out)]
            selected = select_note_rows(marked, captured)
            states = [row for row in selected if row.get("note_key") == "world_state"]
            assert len(states) == (1 if value else 0)
            if states:
                assert value in states[0]["content"]
            assert [row for row in selected if not row.get("note_key") and row in base] == [row for row in base if not row.get("note_key")]
            store.append(assistant_text_message("response"))
    finally:
        actual.clear()


def test_changed_state_preserves_actual_frozen_head_cold_file_and_restart(monkeypatch, tmp_path):
    wp = importlib.import_module("memory.wsc_projection")
    for name, value in {"XEYO_WSC": "1", "XEYO_WSC_FROZEN_HEAD": "1",
                        "XEYO_WSC_CADENCE_ABSORB": "0", "XEYO_WSC_HEAD_STORE": "1",
                        "XEYO_WSC_OFFLINE": "1", "XEYO_HOME": str(tmp_path / "home")}.items():
        monkeypatch.setenv(name, value)
    wp._STATE.clear()
    run = StateLifecycle(reuse_equal_state=False, persist="late", storage="append")
    raw = synth_session(turns=26) + [note(1, "first")]
    working = WorkingSnapshot(session_id="append-state-cold-history")

    def emit(rows, *, fold=False):
        source = run.prepare(rows)
        if fold:
            working.compact_cursor = c2_cut_index(source, None)
        out = wp.project_c2_messages(source, working, cwd=str(tmp_path))
        assert out is not None
        return run.finish(out, fold=fold), source

    try:
        with install_note_exclusion():
            emit(raw, fold=True)
            raw2 = raw + [msg_asst_text("response")]
            emit(raw2)
            more = []
            for i in range(4):
                uid = f"append-{i}"
                more += [msg_asst_use(uid, "Read", {"file_path": "src/login.py"}),
                         msg_tool(uid, "Read", "retained file evidence " * 100)]
            raw3 = raw2 + more
            _, before = emit(raw3, fold=True)
            key = wp._state_key(working.session_id, str(tmp_path))
            previous = wp._STATE[key]
            index = next(i for i, row in enumerate(before) if row.get("note_key"))
            assert previous.region_end > index
            head = previous.head
            cold_path = Path(previous.view_path)
            cold_bytes = cold_path.read_bytes()
            assert previous.cold.texts[index] == "active=1"
            delivered, source = emit(raw3 + [note(0, "second"), msg_asst_text("new state")])
            assert source[:len(before)] == before
            assert wp._STATE[key].head == head
            assert wp._STATE[key].view_path == str(cold_path)
            assert cold_path.read_bytes() == cold_bytes
            assert "active=1" not in head
            assert [row["content"] for row in delivered if row.get("note_key")] == ["active=0"]
            wp._STATE.clear()
            restored = wp.project_c2_messages(source, working, cwd=str(tmp_path))
            assert restored[0]["content"] == head
            assert cold_path.read_bytes() == cold_bytes
            assert run.preview(restored) == delivered
            from memory.wsc_head_store import load
            saved = load(working.session_id, cwd=str(tmp_path), cursor=working.compact_cursor,
                         messages=source, allow_advance=True)
            assert saved.view_path == str(cold_path)
            # Restart restores emission bytes without restoring transient _STATE.
            # The next real fold must fork a cold generation instead of overwrite.
            emit(raw3 + [note(0, "second"), msg_asst_text("new state")] + more, fold=True)
            assert Path(wp._STATE[key].view_path) != cold_path
            assert cold_path.read_bytes() == cold_bytes
    finally:
        wp._STATE.clear()
