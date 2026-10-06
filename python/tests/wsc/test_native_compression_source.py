"""Automatic/manual consumers share source coordinates without altering exports."""
from types import SimpleNamespace

import pytest

from memory.working import WorkingSnapshot
from memory.wsc_source_layout import APPEND, LEGACY
from msgtypes.message import user_message, system_note, assistant_text_message
from session.compression_source import compression_messages
from session.message_store import MessageStore


@pytest.mark.parametrize("layout", [LEGACY, APPEND])
@pytest.mark.parametrize("entry", ["slash", "http"])
def test_real_manual_entrypoint_receives_native_source(monkeypatch, layout, entry):
    from memory import runtime, working
    from slash.dispatch import DispatchContext, _cmd_compact
    from server.routers import memory as router

    store = MessageStore([user_message("request"), system_note("old", key="state", fp="1"),
                          assistant_text_message("result"), system_note("new", key="state", fp="2"),
                          user_message("follow-up")])
    snapshot = WorkingSnapshot(session_id="native-manual", compression_source_layout=layout,
                               compression_source_transition_enabled=layout == APPEND)
    session = SimpleNamespace(messages=store, working=snapshot, session_id=snapshot.session_id)
    engine = SimpleNamespace(_session=session)
    api = store.as_api_messages()
    expected = compression_messages(store, snapshot)
    received = []
    monkeypatch.setattr(runtime, "force_compact", lambda rows, state, **kw: received.append((rows, state)))
    monkeypatch.setattr(working, "flush", lambda *args: None)
    if entry == "slash":
        result = _cmd_compact(DispatchContext(engine=engine), "")
        assert result.result["ok"]
    else:
        monkeypatch.setattr(router, "_pool", SimpleNamespace(get_if_present=lambda sid: engine))
        assert router.manual_compact(router.CompactBody(session_id=snapshot.session_id))["ok"]
    assert len(received) == 1
    assert received[0][0] is expected and received[0][1] is snapshot
    assert [r["content"] for r in expected if r.get("note_key")] == (
        ["old", "new"] if layout == APPEND else ["new"])
    assert store.as_api_messages() is api
    assert [r["content"] for r in api if r.get("note_key")] == ["new"]
