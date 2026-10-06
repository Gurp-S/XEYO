from msgtypes.message import assistant_text_message, system_note, user_message
from evals.wsc_state_reuse import StateReuseStore as MessageStore


def test_visible_identical_note_keeps_api_prefix_and_history():
    first = system_note("active=1", key="world_state", fp="same")
    store = MessageStore([user_message("request"), first, assistant_text_message("result")], reuse_equal_state=True)
    before = store.as_api_messages()
    store.note_fingerprints(projected=before)
    store.append(system_note("active=1", key="world_state", fp="same"))
    store.append(user_message("next"))
    assert store.as_api_messages()[:len(before)] == before
    assert len(store.items) == 5
    assert store.note_fingerprints(start=1) == {("world_state", "same")}


def test_fold_reinjection_and_changed_state_still_replace():
    store = MessageStore([system_note("active=1", key="world_state", fp="same"), assistant_text_message("result")], reuse_equal_state=True)
    store.as_api_messages()
    store.note_fingerprints(start=1)
    store.append(system_note("active=1", key="world_state", fp="same"))
    assert [r["content"] for r in store.as_api_messages()] == ["result", "active=1"]
    store.note_fingerprints(projected=store.as_api_messages())
    store.append(system_note("active=0", key="world_state", fp="same"))
    assert [r["content"] for r in store.as_api_messages()] == ["result", "active=0"]
    store.retract_note("world_state")
    assert not store.note_fingerprints()


def test_off_and_restart_have_no_unsupported_visibility_assumption():
    initial = [system_note("same", key="x", fp="same"), assistant_text_message("result")]
    for enabled in (False, True):
        store = MessageStore(list(initial), reuse_equal_state=enabled)
        store.as_api_messages()
        store.append(system_note("same", key="x", fp="same"))
        # No visibility receipt => latest position, including a restarted store.
        assert [r["content"] for r in store.as_api_messages()] == ["result", "same"]


def test_channel_policy_and_pair_repair_preserve_visibility_indices():
    from msgtypes.message import ToolUse, tool_result_message
    store = MessageStore([
        assistant_text_message("", [ToolUse(id="c", name="Read", input={})]),
        system_note("same", key="x", fp="same"),
        tool_result_message("c", "Read", "result"),
    ], reuse_equal_state=True)
    assert store.note_fingerprints(start=2) == {("x", "same")}
    before = store.as_api_messages()
    store.note_fingerprints(projected=before)
    store.append(system_note("same", key="x", fp="same"))
    assert store.as_api_messages() == before
    store.set_note_policy(False)
    assert not store.note_fingerprints()


def test_wsc_absorbs_beyond_cursor_so_raw_slice_is_not_visibility():
    store = MessageStore([
        user_message("request"), system_note("active=1", key="world_state", fp="same"),
        assistant_text_message("result"), user_message("next"),
    ], reuse_equal_state=True)
    api = store.as_api_messages()
    # cursor=1, actual WSC tail starts at 3. The note was absorbed.
    actual = [{"role": "assistant", "content": "summary"}] + api[3:]
    assert store.note_fingerprints(start=1) == {("world_state", "same")}
    assert store.note_fingerprints(projected=actual) == set()
    store.append(system_note("active=1", key="world_state", fp="same"))
    assert store.as_api_messages()[-1]["content"] == "active=1"


def test_changed_or_partial_projected_body_does_not_authorize_reuse():
    store = MessageStore([system_note("complete body", key="x", fp="same")], reuse_equal_state=True)
    api = store.as_api_messages()
    assert store.note_fingerprints(projected=[{**api[0], "content": "complete…"}]) == set()
    store.append(assistant_text_message("result"))
    store.append(system_note("complete body", key="x", fp="same"))
    assert [r["content"] for r in store.as_api_messages()] == ["result", "complete body"]
