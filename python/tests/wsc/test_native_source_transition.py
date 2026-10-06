from types import SimpleNamespace

import pytest

from memory.working import WorkingSnapshot
from memory.wsc_source_layout import APPEND, LEGACY
from memory import wsc_source_transition as transition, wsc_head_store as heads
from msgtypes.message import user_message, system_note, assistant_text_message
from session.message_store import MessageStore


def test_diagnosis_reused_but_snapshot_cursor_and_workspace_are_separate(monkeypatch):
    calls = []
    monkeypatch.setattr(transition, "invalid_persisted_source", lambda *a: calls.append(a) or False)
    store = MessageStore([user_message("request")])
    state = WorkingSnapshot(session_id="native-diagnosis", compression_source_transition_enabled=True)
    for _ in range(8):
        assert not transition.prepare_compression_source(store, state, cwd="a")
    assert len(calls) == 1
    state.compact_cursor = 1
    transition.prepare_compression_source(store, state, cwd="a")
    transition.prepare_compression_source(store, state, cwd="b")
    other = WorkingSnapshot(session_id=state.session_id, compression_source_transition_enabled=True)
    transition.prepare_compression_source(store, other, cwd="b")
    store.append(assistant_text_message("new"))
    transition.prepare_compression_source(store, other, cwd="b")
    assert len(calls) == 5


@pytest.mark.parametrize("entry", ["slash", "http"])
def test_manual_native_migration_is_one_fold_in_session_workspace(monkeypatch, tmp_path, entry):
    from memory import runtime, working
    from slash.dispatch import DispatchContext, _cmd_compact
    from server.routers import memory as router
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    cwd = str(tmp_path / "actual-workspace")
    store = MessageStore([user_message("request"), system_note("old", key="state", fp="1"),
                          assistant_text_message("result"), user_message("follow-up")])
    state = WorkingSnapshot(session_id="native-migration", compact_cursor=2,
        compression_source_transition_enabled=True, todos=[{"content":"remain", "status":"pending"}])
    heads.save(state.session_id, text="old head", cwd=cwd, cursor=2, region_end=2,
               messages=store.as_api_messages())
    store.append(system_note("new", key="state", fp="2"))
    session = SimpleNamespace(messages=store, working=state, session_id=state.session_id)
    engine = SimpleNamespace(_session=session)
    folds = []
    monkeypatch.setattr(runtime, "force_compact", lambda rows, snap, **kw: folds.append((rows, kw)))
    monkeypatch.setattr(working, "flush", lambda *a: None)
    if entry == "slash":
        assert _cmd_compact(DispatchContext(engine=engine, workspace=cwd), "").result["ok"]
    else:
        monkeypatch.setattr(router, "_pool", SimpleNamespace(cwd="different-default",
            get_if_present=lambda sid:engine, session_cwd=lambda sid:cwd))
        assert router.manual_compact(router.CompactBody(session_id=state.session_id))["ok"]
    assert state.compression_source_layout == APPEND
    assert state.compact_cursor == 0 and state.todos[0]["content"] == "remain"
    assert len(folds) == 1 and folds[0][1]["cwd"] == cwd
    assert [r["content"] for r in folds[0][0] if r.get("note_key")] == ["old", "new"]


def test_default_does_not_diagnose_or_change_source(monkeypatch):
    monkeypatch.setattr(transition, "invalid_persisted_source", lambda *a: pytest.fail("default diagnosis"))
    state = WorkingSnapshot(session_id="default-source", compact_cursor=5)
    assert not transition.prepare_compression_source(MessageStore(), state, cwd="x")
    assert state.compression_source_layout == LEGACY and state.compact_cursor == 5


def test_oversized_head_cannot_trigger_migration_or_load(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    rows = [{"role": "user", "content": "request"}]
    heads.save("oversized", text="head", cwd="x", cursor=1, region_end=1, messages=rows)
    monkeypatch.setattr(heads, "_MAX_BYTES", 1)
    assert heads.load("oversized", cwd="x", cursor=1, messages=rows) is None
    assert not heads.source_changed("oversized", cwd="x", cursor=1, messages=rows)


def test_experimental_transition_enable_is_not_persisted(monkeypatch, tmp_path):
    import json
    from memory import working
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    state = WorkingSnapshot(session_id="transient-source-flag", compression_source_transition_enabled=True)
    working.flush(state.session_id, state)
    payload = json.loads(working.path_for(state.session_id).read_text(encoding="utf-8"))
    assert "compression_source_transition_enabled" not in payload
    assert not working.hydrate(state.session_id).compression_source_transition_enabled
