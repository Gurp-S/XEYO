import json
from types import SimpleNamespace

import pytest

from evals.wsc_source_transition import invalid_persisted_source
from memory import wsc_head_store as heads


@pytest.mark.parametrize("bad", ["missing", "json", "version", "cwd", "cursor", "end", "seal", "text", "truncated"])
def test_unproven_head_failure_never_triggers_source_migration(monkeypatch, tmp_path, bad):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    state = SimpleNamespace(session_id="diagnose", compact_cursor=2)
    rows = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "answer"}]
    heads.save(state.session_id, text="head", cwd="workspace", cursor=2, region_end=2, messages=rows)
    path = heads.path_for(state.session_id)
    record = json.loads(path.read_text())
    if bad == "missing":
        path.unlink()
    elif bad == "json":
        path.write_text("{", encoding="utf-8")
    elif bad == "truncated":
        rows = rows[:1]
    else:
        key, value = {"version": ("ver", 99), "cwd": ("cwd", "other"),
                      "cursor": ("cursor", 1), "end": ("region_end", True),
                      "seal": ("seal", "invalid"), "text": ("text", "")}[bad]
        record[key] = value
        path.write_text(json.dumps(record), encoding="utf-8")
    assert not invalid_persisted_source(state, rows, "workspace")


def test_valid_persisted_record_distinguishes_tail_append_from_frozen_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
    state = SimpleNamespace(session_id="diagnose", compact_cursor=2)
    rows = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "answer"}]
    heads.save(state.session_id, text="head", cwd="workspace", cursor=2, region_end=2, messages=rows)
    saved = heads.path_for(state.session_id).read_bytes()
    tail = rows + [{"role": "user", "content": "new request"}]
    assert not invalid_persisted_source(state, tail, "workspace")
    revised = [{"role": "user", "content": "changed"}] + tail[1:]
    assert invalid_persisted_source(state, revised, "workspace")
    assert heads.path_for(state.session_id).read_bytes() == saved


def test_unchanged_source_diagnosis_is_not_repeated_for_each_getter(monkeypatch, tmp_path):
    from evals.wsc_query_source import ConditionalQuerySource
    from memory.working import WorkingSnapshot
    from msgtypes.message import user_message, assistant_text_message
    from session.message_store import MessageStore
    import evals.wsc_source_transition as transition
    store = MessageStore([user_message("request")])
    snapshot = WorkingSnapshot(session_id="diagnosis-reuse")
    source = ConditionalQuerySource(store, snapshot, str(tmp_path))
    observed = []
    monkeypatch.setattr(transition, "invalid_persisted_source", lambda *args: observed.append(1) or False)
    try:
        for _ in range(8):
            source.as_api_messages()
        assert len(observed) == source.source_checks == 1
        store.append(assistant_text_message("new response"))
        for _ in range(8):
            source.as_api_messages()
        assert len(observed) == source.source_checks == 2
    finally:
        source.close()
