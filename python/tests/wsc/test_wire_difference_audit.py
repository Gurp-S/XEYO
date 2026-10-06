from evals.wsc_wire_difference import first_difference, state_identities


def test_appending_rows_and_changing_old_rows_are_distinct():
    head = {"role":"assistant", "content":"head"}
    old = [head, {"role":"user", "content":"fact"}]
    assert first_difference(old, old+[dict(role="assistant", content="new")])["kind"] == "append_only"
    assert first_difference(old, [head, dict(role="user", content="changed")])["kind"] == "ordinary_tail_difference"
    assert first_difference(old, [head])["kind"] == "suffix_removed"


def test_state_body_matching_survives_provider_metadata_stripping():
    old_state = dict(role="user", content="old state", note_key="world_state")
    current_state = dict(role="user", content="new state", note_key="world_state")
    old = [dict(role="assistant", content="head"), {k:v for k,v in old_state.items() if k!="note_key"}]
    current = [old[0], dict(role="assistant",content="new response"),
               {k:v for k,v in current_state.items() if k!="note_key"}]
    result = first_difference(old, current, state_identities([old_state]), state_identities([current_state]))
    assert result["kind"] == "state_row_changed_or_moved"
    assert result["equal_rows"] == 1 and not result["previous_row_still_present"]
    assert "old state" not in str(result) and "new state" not in str(result)


def test_different_metadata_does_not_guess_state_from_arbitrary_quotation():
    old = [dict(role="assistant", content="head"), dict(role="user", content="quoted state text")]
    current = [old[0], dict(role="user", content="ordinary correction")]
    assert first_difference(old, current)["kind"] == "ordinary_tail_difference"
