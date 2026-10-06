from evals.wsc_equal_state import VisibleEqualState
from msgtypes.message import Message


def note(value, *, role="user", retracted=False, fp="same"):
    return Message(role=role, content=value, note_key="world_state", note_fp=fp, note_retracted=retracted)


def test_equal_visible_state_keeps_prefix_and_one_authoritative_value():
    selector = VisibleEqualState()
    first, answer, second = note("active=1"), Message(role="assistant", content="result"), note("active=1")
    assert selector.select([first, answer], include_system_notes=True) == [first, answer]
    selector.record_tail(0)
    assert selector.select([first, answer, second], include_system_notes=True) == [first, answer]


def test_absorbed_state_requires_reinjection_even_when_identical():
    selector = VisibleEqualState()
    first, second = note("active=1"), note("active=1")
    selector.select([first], include_system_notes=True)
    selector.record_tail(1)
    assert selector.select([first, second], include_system_notes=True) == [second]


def test_changed_content_cannot_be_hidden_by_equal_fingerprint():
    selector = VisibleEqualState()
    first, second = note("active=1"), note("active=0")
    selector.select([first], include_system_notes=True)
    selector.record_tail(0)
    assert selector.select([first, second], include_system_notes=True) == [second]


def test_change_and_return_or_retraction_cannot_reuse_old_position():
    selector = VisibleEqualState()
    first, changed, returned = note("A"), note("B"), note("A")
    selector.select([first], include_system_notes=True)
    selector.record_tail(0)
    assert selector.select([first, changed, returned], include_system_notes=True) == [returned]
    selector.record_tail(0)
    returned.note_retracted = True
    replacement = note("A")
    assert selector.select([first, changed, returned, replacement], include_system_notes=True) == [replacement]


def test_system_policy_and_history_rollback_do_not_retain_hidden_state():
    selector = VisibleEqualState()
    first = note("A", role="system")
    selector.select([first], include_system_notes=True)
    selector.record_tail(0)
    assert selector.select([first], include_system_notes=False) == []
    new = note("B")
    assert selector.select([new], include_system_notes=True) == [new]


def test_identity_metadata_changes_require_latest_version():
    selector = VisibleEqualState()
    first, second = note("A", fp="old"), note("A", fp="new")
    selector.select([first], include_system_notes=True)
    selector.record_tail(0)
    assert selector.select([first, second], include_system_notes=True) == [second]
