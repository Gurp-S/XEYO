import gc
import weakref

from evals.wsc_source_contract import APPEND, LEGACY, source_messages
from evals.wsc_source_reader import SourceReader
from msgtypes.message import (
    user_message, system_note, assistant_text_message, tool_result_message, ToolUse,
)
from session.message_store import MessageStore


def test_reuses_source_until_native_mutation_and_keeps_api_selection():
    store = MessageStore([user_message("request"), system_note("old", key="state", fp="1"),
                          system_note("new", key="state", fp="2")])
    reader = SourceReader()
    previous = None
    mutations = [lambda: None,
                 lambda: store.append(assistant_text_message("answer")),
                 lambda: store.insert(1, user_message("additional fact")),
                 lambda: store.retract_note("state"),
                 lambda: store.set_note_policy(False),
                 lambda: store.replace([user_message("replaced history")])]
    for mutate in mutations:
        mutate()
        api = store.as_api_messages()
        expected = source_messages(store, APPEND)
        actual = reader.read(store, APPEND)
        assert actual == expected
        assert actual is reader.read(store, APPEND)
        assert reader.read(store, LEGACY) is api
        assert store.as_api_messages() is api
        assert actual is not previous
        previous = actual


def test_pairing_cleanup_is_shared_with_api_and_not_repeated_on_cache_hit():
    store = MessageStore([user_message("start"),
                          assistant_text_message("", [ToolUse("call", "Read", {})]),
                          system_note("current", key="state", fp="1"),
                          tool_result_message("call", "Read", "file body"),
                          tool_result_message("orphan", "Read", "unpaired")])
    reader = SourceReader()
    expected = source_messages(MessageStore(list(store.items)), APPEND)
    assert reader.read(store, APPEND) == expected
    assert [item.role for item in store.items] == ["user", "assistant", "tool", "system"]
    api = store.as_api_messages()
    assert reader.read(store, APPEND) is reader.read(store, APPEND)
    assert store.as_api_messages() is api


def test_cache_does_not_keep_closed_sessions_alive_or_mix_session_rows():
    reader = SourceReader()
    first = MessageStore([user_message("one")])
    second = MessageStore([user_message("two")])
    assert reader.read(first, APPEND) != reader.read(second, APPEND)
    ref = weakref.ref(first)
    del first
    gc.collect()
    assert ref() is None
    assert len(reader._cache) == 1
